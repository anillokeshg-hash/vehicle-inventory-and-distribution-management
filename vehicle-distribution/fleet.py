"""Vehicle inventory & distribution engine: stock, sales forecast, transfer planning, aging."""
import math

import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge

import data

MIN_DAYS = 10        # dealer below this many days of supply needs replenishment
TARGET_DAYS = 21     # replenish up to this many days of supply
OVERSTOCK_DAYS = 45  # dealer above this can give stock away
COST_PER_KM = 18.0   # INR per vehicle per km
ROAD_FACTOR = 1.3
TRUCK_KM_PER_DAY = 450


def _features(dates: pd.DatetimeIndex, start: pd.Timestamp) -> np.ndarray:
    t = ((dates - start).days.values).reshape(-1, 1) / 100.0
    return np.hstack([t, np.eye(7)[dates.dayofweek.values]])


def _distance_km(a, b) -> float:
    la1, lo1, la2, lo2 = map(math.radians, [a.lat, a.lon, b.lat, b.lon])
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 6371 * 2 * math.asin(math.sqrt(h)) * ROAD_FACTOR


class FleetManager:
    def __init__(self):
        self.loc = data.LOCATIONS
        self.sales = data.generate_sales_history()
        self.vehicles = data.generate_vehicles()
        self.transfers: list[dict] = []
        self._rng = np.random.default_rng(5)
        self._fit_forecasts()

    # ---------- 1. Sales forecasting ----------
    def _fit_forecasts(self):
        self.daily = {}      # (dealer, model) -> avg forecast units/day over next 14 days
        self.fc_series = {}  # (dealer, model) -> list of daily forecasts
        future = pd.date_range(data.TODAY, periods=14)
        for (d, m), h in self.sales.groupby(["dealer_id", "model"]):
            h = h.sort_values("date")
            start = h.date.min()
            reg = Ridge(alpha=0.1).fit(_features(pd.DatetimeIndex(h.date), start), h.units.values)
            pred = np.clip(reg.predict(_features(future, start)), 0, None)
            self.fc_series[(d, m)] = pred
            self.daily[(d, m)] = max(float(pred.mean()), 0.05)

    def forecast(self, dealer_id: str, model: str) -> list[dict]:
        return [{"date": d.strftime("%Y-%m-%d"), "predicted_units": round(float(v), 2)}
                for d, v in zip(pd.date_range(data.TODAY, periods=14), self.fc_series[(dealer_id, model)])]

    # ---------- 2. Inventory ----------
    def _counts(self, status: str, col: str) -> dict:
        v = self.vehicles[self.vehicles.status == status]
        return v.groupby([col, "model"]).size().to_dict()

    def inventory(self) -> list[dict]:
        stock, incoming = self._counts("IN_STOCK", "location_id"), self._counts("IN_TRANSIT", "transit_to")
        rows = []
        for lid, loc in self.loc.iterrows():
            for m in data.MODELS:
                s, inc = int(stock.get((lid, m), 0)), int(incoming.get((lid, m), 0))
                row = {"location_id": lid, "location": loc["name"], "type": loc["type"], "model": m,
                       "in_stock": s, "incoming": inc}
                if loc["type"] == "dealer":
                    daily = self.daily[(lid, m)]
                    dos = (s + inc) / daily
                    row.update({"forecast_per_day": round(daily, 2), "days_of_supply": round(dos, 1),
                                "status": "LOW" if dos < MIN_DAYS else "OVERSTOCK" if dos > OVERSTOCK_DAYS else "OK"})
                rows.append(row)
        return rows

    def vehicle_list(self, location=None, model=None, status=None, limit=200) -> list[dict]:
        v = self.vehicles
        if location: v = v[v.location_id == location]
        if model: v = v[v.model == model]
        if status: v = v[v.status == status]
        v = v.head(limit).copy()
        v["arrival_date"] = v.arrival_date.dt.strftime("%Y-%m-%d")
        v["age_days"] = (data.TODAY - pd.to_datetime(v.arrival_date)).dt.days
        return v.where(v.notna(), None).to_dict(orient="records")

    # ---------- 3. Distribution planning ----------
    def distribution_plan(self) -> list[dict]:
        stock, incoming = self._counts("IN_STOCK", "location_id"), self._counts("IN_TRANSIT", "transit_to")
        avail = {}  # (source, model) -> vehicles we can give away
        needs = []
        for lid, loc in self.loc.iterrows():
            for m in data.MODELS:
                s = int(stock.get((lid, m), 0))
                if loc["type"] == "hub":
                    avail[(lid, m)] = s
                    continue
                daily, inc = self.daily[(lid, m)], int(incoming.get((lid, m), 0))
                dos = (s + inc) / daily
                target = math.ceil(TARGET_DAYS * daily)
                if dos < MIN_DAYS:
                    needs.append((dos, lid, m, target - s - inc))
                elif dos > OVERSTOCK_DAYS and s > target:
                    avail[(lid, m)] = s - target
        plan = []
        for dos, dest, m, need in sorted(needs):
            sources = sorted((k for k in avail if k[1] == m and avail[k] > 0 and k[0] != dest),
                             key=lambda k: _distance_km(self.loc.loc[k[0]], self.loc.loc[dest]))
            for src, _ in sources:
                if need <= 0:
                    break
                qty = min(need, avail[(src, m)])
                dist = _distance_km(self.loc.loc[src], self.loc.loc[dest])
                plan.append({"from_id": src, "from": self.loc.loc[src, "name"],
                             "to_id": dest, "to": self.loc.loc[dest, "name"], "model": m, "qty": int(qty),
                             "distance_km": round(dist), "est_cost_inr": round(dist * COST_PER_KM * qty),
                             "eta_days": math.ceil(dist / TRUCK_KM_PER_DAY) + 1,
                             "priority": "URGENT" if dos < 5 else "NORMAL",
                             "reason": f"Dealer has {dos:.1f} days of supply",
                             "source_type": self.loc.loc[src, "type"]})
                avail[(src, m)] -= qty
                need -= qty
        return plan

    def execute_plan(self) -> list[dict]:
        done = []
        v = self.vehicles
        for line in self.distribution_plan():
            mask = ((v.location_id == line["from_id"]) & (v.model == line["model"]) & (v.status == "IN_STOCK"))
            idx = v[mask].sort_values("arrival_date").index[:line["qty"]]  # oldest first (FIFO)
            tid = len(self.transfers) + 1
            eta = (data.TODAY + pd.Timedelta(days=line["eta_days"])).strftime("%Y-%m-%d")
            v.loc[idx, "status"] = "IN_TRANSIT"
            v.loc[idx, "transit_to"] = line["to_id"]
            v.loc[idx, "eta"] = eta
            v.loc[idx, "transfer_id"] = tid
            rec = {"transfer_id": tid, **{k: line[k] for k in
                   ("from", "to", "to_id", "model", "qty", "distance_km", "est_cost_inr", "priority")},
                   "dispatched": data.TODAY.strftime("%Y-%m-%d"), "eta": eta, "status": "IN_TRANSIT"}
            self.transfers.append(rec)
            done.append(rec)
        return done

    def receive_transfer(self, transfer_id: int):
        t = next((x for x in self.transfers if x["transfer_id"] == transfer_id and x["status"] == "IN_TRANSIT"), None)
        if not t:
            return None
        idx = self.vehicles[self.vehicles.transfer_id == transfer_id].index
        self.vehicles.loc[idx, "location_id"] = t["to_id"]
        self.vehicles.loc[idx, "status"] = "IN_STOCK"
        for col in ("transit_to", "eta", "transfer_id"):
            self.vehicles.loc[idx, col] = None
        t["status"] = "DELIVERED"
        return t

    def receive_all(self) -> int:
        n = 0
        for t in list(self.transfers):
            if t["status"] == "IN_TRANSIT" and self.receive_transfer(t["transfer_id"]):
                n += 1
        return n

    # ---------- 4. Sales ----------
    def sell(self, dealer_id: str, model: str, qty: int = 1) -> int:
        """Sell vehicles at a dealer, oldest stock first."""
        v = self.vehicles
        mask = (v.location_id == dealer_id) & (v.model == model) & (v.status == "IN_STOCK")
        idx = v[mask].sort_values("arrival_date").index[:qty]
        v.loc[idx, "status"] = "SOLD"
        return len(idx)

    def simulate_sales(self, days: int = 7) -> int:
        total = 0
        for (d, m), daily in self.daily.items():
            total += self.sell(d, m, int(self._rng.poisson(daily * days)))
        return total

    # ---------- 5. Aging & alerts ----------
    def aging_report(self, min_age: int = 60) -> list[dict]:
        v = self.vehicles[self.vehicles.status == "IN_STOCK"].copy()
        v["age"] = (data.TODAY - v.arrival_date).dt.days
        old = v[v.age >= min_age]
        out = []
        for (lid, m), g in old.groupby(["location_id", "model"]):
            oldest = int(g.age.max())
            disc = 8 if oldest > 90 else 4
            out.append({"location": self.loc.loc[lid, "name"], "model": m, "aged_units": len(g),
                        "oldest_days": oldest, "suggested_discount_pct": disc,
                        "value_at_risk_inr": int(len(g) * data.MODELS[m])})
        return sorted(out, key=lambda r: -r["oldest_days"])

    def alerts(self) -> list[dict]:
        out = []
        for r in self.inventory():
            if r["type"] != "dealer":
                continue
            if r["status"] == "LOW":
                sev = "critical" if r["days_of_supply"] < 5 else "warning"
                out.append({"severity": sev, "message":
                            f"{r['location']} - {r['model']}: only {r['days_of_supply']} days of supply "
                            f"({r['in_stock']} in stock, {r['incoming']} incoming)."})
            elif r["status"] == "OVERSTOCK":
                out.append({"severity": "info", "message":
                            f"{r['location']} - {r['model']}: overstocked ({r['days_of_supply']} days of supply)."})
        for a in self.aging_report(min_age=90):
            out.append({"severity": "warning", "message":
                        f"{a['location']} - {a['model']}: {a['aged_units']} unit(s) older than 90 days "
                        f"(oldest {a['oldest_days']}d). Suggest {a['suggested_discount_pct']}% discount."})
        order = {"critical": 0, "warning": 1, "info": 2}
        return sorted(out, key=lambda a: order[a["severity"]])

    def summary(self) -> dict:
        v = self.vehicles
        return {"in_stock": int((v.status == "IN_STOCK").sum()),
                "in_transit": int((v.status == "IN_TRANSIT").sum()),
                "sold": int((v.status == "SOLD").sum()),
                "stock_value_inr": int(sum(data.MODELS[m] for m in v[v.status == "IN_STOCK"].model))}

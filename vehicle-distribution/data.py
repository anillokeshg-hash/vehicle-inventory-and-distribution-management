"""Synthetic data: central hubs, dealerships, vehicle models, VIN-level stock and sales history."""
import numpy as np
import pandas as pd

rng = np.random.default_rng(21)
TODAY = pd.Timestamp.today().normalize()

LOCATIONS = pd.DataFrame(
    [
        ("H1", "Chennai Hub", "hub", "Chennai", 13.08, 80.27),
        ("H2", "Delhi Hub", "hub", "Delhi", 28.61, 77.21),
        ("D1", "Mumbai Dealer", "dealer", "Mumbai", 19.08, 72.88),
        ("D2", "Bengaluru Dealer", "dealer", "Bengaluru", 12.97, 77.59),
        ("D3", "Hyderabad Dealer", "dealer", "Hyderabad", 17.38, 78.48),
        ("D4", "Kolkata Dealer", "dealer", "Kolkata", 22.57, 88.36),
        ("D5", "Pune Dealer", "dealer", "Pune", 18.52, 73.86),
        ("D6", "Jaipur Dealer", "dealer", "Jaipur", 26.91, 75.79),
    ],
    columns=["location_id", "name", "type", "city", "lat", "lon"],
).set_index("location_id")

MODELS = {"Hatchback": 650000, "Sedan": 1100000, "SUV": 1600000, "EV": 1900000}  # list price (INR)
COLORS = ["White", "Black", "Silver", "Red", "Blue"]

DEALER_SCALE = {"D1": 1.4, "D2": 1.2, "D3": 1.0, "D4": 0.8, "D5": 1.0, "D6": 0.6}
MODEL_BASE = {"Hatchback": 2.5, "Sedan": 1.5, "SUV": 2.0, "EV": 0.7}  # sales/day at scale 1.0


def generate_sales_history(days: int = 60) -> pd.DataFrame:
    dates = pd.date_range(end=TODAY - pd.Timedelta(days=1), periods=days)
    rows = []
    for d, scale in DEALER_SCALE.items():
        for m, base in MODEL_BASE.items():
            for i, dt in enumerate(dates):
                lam = base * scale * (1.3 if dt.dayofweek >= 5 else 1.0) * (1 + 0.003 * i)
                rows.append((dt, d, m, int(rng.poisson(lam))))
    return pd.DataFrame(rows, columns=["date", "dealer_id", "model", "units"])


def generate_vehicles() -> pd.DataFrame:
    """VIN-level stock. Some dealers start low, some overstocked with aged units."""
    rows, n = [], 0
    for loc_id, loc in LOCATIONS.iterrows():
        for m, base in MODEL_BASE.items():
            if loc.type == "hub":
                count, max_age = int(rng.integers(80, 160)), 40
            else:
                daily = base * DEALER_SCALE[loc_id]
                count, max_age = max(1, int(round(daily * rng.uniform(2, 55)))), 130
            for _ in range(count):
                n += 1
                rows.append((f"VIN{n:06d}", m, str(rng.choice(COLORS)), loc_id, "IN_STOCK",
                             TODAY - pd.Timedelta(days=int(rng.integers(0, max_age))), None, None, None))
    return pd.DataFrame(rows, columns=["vin", "model", "color", "location_id", "status",
                                       "arrival_date", "transit_to", "eta", "transfer_id"])

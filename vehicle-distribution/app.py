"""Flask API + dashboard for Vehicle Inventory and Distribution Management."""
from flask import Flask, jsonify, request, render_template_string

from fleet import FleetManager

app = Flask(__name__)
fm = FleetManager()

DASHBOARD = """
<!doctype html>
<title>Vehicle Distribution</title>
<style>
  body{font-family:system-ui,sans-serif;margin:2rem auto;max-width:1060px;padding:0 1rem;color:#222}
  section{margin:1.8rem 0} table{border-collapse:collapse;width:100%;font-size:14px}
  th,td{border-bottom:1px solid #ddd;padding:6px 8px;text-align:left}
  button{padding:8px 14px;border:0;border-radius:6px;background:#2563eb;color:#fff;cursor:pointer;margin:0 8px 8px 0}
  button.alt{background:#475569}
  .critical,.LOW,.URGENT{color:#b91c1c;font-weight:600}.warning,.OVERSTOCK{color:#b45309}
  .info,.OK{color:#15803d}
  #sum span{display:inline-block;margin-right:24px}
</style>
<h1>Vehicle Inventory and Distribution Management</h1>
<p id="sum"></p>
<p><button onclick="act('/api/distribution/execute')">Execute distribution plan</button>
   <button class="alt" onclick="act('/api/transfers/receive-all')">Receive all arrivals</button>
   <button class="alt" onclick="act('/api/simulate/sales?days=7')">Simulate 7 days of sales</button></p>

<section><h2>Alerts</h2><table id="alerts"></table></section>
<section><h2>Recommended transfers</h2><table id="plan"></table></section>
<section><h2>Transfers</h2><table id="tr"></table></section>
<section><h2>Dealer inventory (lowest days of supply first)</h2><table id="inv"></table></section>
<section><h2>Aging stock (60+ days)</h2><table id="age"></table></section>

<script>
const J = async (u, o) => (await fetch(u, o)).json();
const CLS = ['severity','status','priority'];
const rows = (id, cols, data) => {
  document.getElementById(id).innerHTML = '<tr>' + cols.map(c => `<th>${c}</th>`).join('') + '</tr>' +
    (data.length ? data.map(r => '<tr>' + cols.map(c => `<td class="${CLS.includes(c)?r[c]:''}">${r[c] ?? ''}</td>`).join('') + '</tr>').join('')
                 : `<tr><td colspan="${cols.length}">None</td></tr>`);
};
async function load(){
  const s = await J('/api/summary');
  document.getElementById('sum').innerHTML = `<span><b>${s.in_stock}</b> in stock</span><span><b>${s.in_transit}</b> in transit</span><span><b>${s.sold}</b> sold</span><span>Stock value: <b>₹${(s.stock_value_inr/1e7).toFixed(2)} Cr</b></span>`;
  rows('alerts', ['severity','message'], (await J('/api/alerts')).slice(0, 15));
  rows('plan', ['priority','from','to','model','qty','distance_km','eta_days','est_cost_inr','reason'], await J('/api/distribution/plan'));
  rows('tr', ['transfer_id','from','to','model','qty','eta','status'], await J('/api/transfers'));
  const inv = (await J('/api/inventory')).filter(r => r.type == 'dealer').sort((a,b) => a.days_of_supply - b.days_of_supply);
  rows('inv', ['location','model','in_stock','incoming','forecast_per_day','days_of_supply','status'], inv);
  rows('age', ['location','model','aged_units','oldest_days','suggested_discount_pct','value_at_risk_inr'], await J('/api/aging'));
}
async function act(u){ await J(u, {method:'POST'}); load(); }
load();
</script>
"""


@app.get("/")
def home():
    return render_template_string(DASHBOARD)


@app.get("/api/summary")
def summary():
    return jsonify(fm.summary())


@app.get("/api/inventory")
def inventory():
    return jsonify(fm.inventory())


@app.get("/api/vehicles")
def vehicles():
    return jsonify(fm.vehicle_list(request.args.get("location"), request.args.get("model"),
                                   request.args.get("status"), request.args.get("limit", 200, type=int)))


@app.get("/api/forecast/<dealer_id>/<model>")
def forecast(dealer_id, model):
    if (dealer_id, model) not in fm.fc_series:
        return jsonify(error="unknown dealer/model"), 404
    return jsonify(fm.forecast(dealer_id, model))


@app.get("/api/distribution/plan")
def plan():
    return jsonify(fm.distribution_plan())


@app.post("/api/distribution/execute")
def execute():
    return jsonify(transfers=fm.execute_plan())


@app.get("/api/transfers")
def transfers():
    return jsonify(fm.transfers)


@app.post("/api/transfers/<int:tid>/receive")
def receive(tid):
    t = fm.receive_transfer(tid)
    return (jsonify(t), 200) if t else (jsonify(error="not found or already delivered"), 404)


@app.post("/api/transfers/receive-all")
def receive_all():
    return jsonify(delivered=fm.receive_all())


@app.post("/api/sell")
def sell():
    b = request.get_json(force=True)
    sold = fm.sell(b["dealer_id"], b["model"], int(b.get("qty", 1)))
    return (jsonify(sold=sold), 200) if sold else (jsonify(error="no stock to sell"), 409)


@app.post("/api/simulate/sales")
def simulate_sales():
    return jsonify(sold=fm.simulate_sales(request.args.get("days", 7, type=int)))


@app.get("/api/aging")
def aging():
    return jsonify(fm.aging_report())


@app.get("/api/alerts")
def alerts():
    return jsonify(fm.alerts())


if __name__ == "__main__":
    app.run(debug=True, port=5003)

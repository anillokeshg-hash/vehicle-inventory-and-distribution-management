# Vehicle Inventory and Distribution Management

A simple base project for tracking vehicle stock (down to the VIN) across hubs and dealerships and
planning how to distribute vehicles to where they will sell. All data is synthetic (see `data.py`).

## What it models
- 2 central hubs (Chennai, Delhi) and 6 dealerships
- 4 vehicle models (Hatchback, Sedan, SUV, EV) with list prices
- VIN-level records: model, colour, location, arrival date, status (`IN_STOCK`, `IN_TRANSIT`, `SOLD`)
- 60 days of dealer sales history

## Features
| Module | What it does | Method |
|---|---|---|
| Sales forecasting | Predicts daily sales per dealer and model | Ridge regression (weekday + trend) |
| Inventory | Stock, incoming units and days of supply per location/model | Aggregation + forecast |
| Distribution planning | Recommends transfers from hubs and overstocked dealers to low-stock dealers | Greedy allocation, nearest source first, min/target days of supply |
| Transfers | Dispatches oldest vehicles first (FIFO), tracks transit, receives at destination | VIN status workflow |
| Aging stock | Finds vehicles in stock 60+ days with suggested discounts and value at risk | Rule-based |
| Alerts | Low stock, overstock and aged inventory | Thresholds |

Rules in `fleet.py`: replenish when below 10 days of supply, up to 21 days; dealers above 45 days are overstocked.

## Run
```bash
pip install -r requirements.txt
python app.py
```
Open http://127.0.0.1:5003

Try it: click **Execute distribution plan**, then **Receive all arrivals**, then **Simulate 7 days of sales**
and watch alerts and recommendations change.

## API
- `GET  /api/summary`, `GET /api/inventory`, `GET /api/vehicles?location=D1&model=SUV&status=IN_STOCK`
- `GET  /api/forecast/<dealer_id>/<model>`
- `GET  /api/distribution/plan`, `POST /api/distribution/execute`
- `GET  /api/transfers`, `POST /api/transfers/<id>/receive`, `POST /api/transfers/receive-all`
- `POST /api/sell` with `{"dealer_id": "D1", "model": "SUV", "qty": 1}`
- `POST /api/simulate/sales?days=7`
- `GET  /api/aging`, `GET /api/alerts`

## Structure
```
app.py     Flask API + dashboard
fleet.py   Forecasting, inventory, distribution planning, aging, alerts
data.py    Synthetic locations, models, VIN stock, sales history
requirements.txt
```

## Ideas to extend
Connect a DMS/ERP and database, add colour/trim-level planning, route optimisation for multi-stop trucks,
dealer allocation fairness rules, and real-time GPS tracking.

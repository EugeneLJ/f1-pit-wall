
## Power-unit rules (benchmark 2.1.0) — these replace the "small pool of free replacement units" rule above

- **Allocation per driver.** Each driver may use 2 units of each element type (ICE, turbo, energy_store) this season without penalty. The starting units count.
- **Team stock.** A `REPLACE` fits a new unit from the team's stock, `resource_inventory["stock:<type>"]`. Both drivers share it and it is never refilled. An element may keep running above the wear limit, with the published pace and reliability cost. A `REPLACE` is legal only while stock is left.
- **Grid penalties.** Each unit beyond a driver's allocation costs grid places at the race where it is first used: 4 places for the first extra unit of a type, 2 for each later one.
  - Places from several replacements at the same race add up.
  - A driver with more than 5 places starts behind all other cars, in qualifying order.
  - Otherwise the driver drops that many places from the qualifying position.
- **Where to look.** `controlled_drivers.*.components.*.replace_cost_if_only_replacement` shows each element's allocation, the units used, the places it would cost and the stock left.
- **Exact rules.** `f1ctl rules` → `power_unit_rules` has the rule text. It also says which parts follow the FIA 2026 sporting regulations and which are scaled for an 8-race, 8-car season.

"""Interactive CLI for inspecting and running a generated city.

    python -m citysim.cli cities/demo_ford
    python -m citysim.cli cities/demo_ford --run 1000      # headless: run until collapse/horizon
"""
from __future__ import annotations
import argparse, sys
from pathlib import Path

from .simulation import Simulation, HORIZON_YEARS
from .validate import load_city

MENU = """
 [n] advance one month        [y] skip N years (month by month)
 [1] City information         [2] Population and requirements
 [3] Productive sectors       [4] Stocks and reserves
 [5] Material flows (last month)
 [6] Economic state and yearly history
 [7] Conditions of material reproduction
 [r] final report (after the run ends)   [q] quit
"""


def fmt(v: float) -> str:
    if abs(v) >= 100:
        return f"{v:,.0f}"
    return f"{v:,.2f}"


def read_key(prompt: str = "> ") -> str:
    """Single keypress where possible, otherwise a line."""
    print(prompt, end="", flush=True)
    try:
        import termios, tty
        if sys.stdin.isatty():
            fd = sys.stdin.fileno()
            old = termios.tcgetattr(fd)
            try:
                tty.setcbreak(fd)
                ch = sys.stdin.read(1)
            finally:
                termios.tcsetattr(fd, termios.TCSADRAIN, old)
            print(ch)
            return ch.lower()
    except Exception:
        pass
    return (sys.stdin.readline().strip() or " ")[:1].lower()


class App:
    def __init__(self, path: Path):
        self.path = path
        self.city, self.spec = load_city(path)
        self.sim = Simulation(self.city, self.spec)
        self.goods = {g.id: g for g in self.spec.goods}
        self.names = {s.id: s.name for s in self.spec.sectors}

    # -- header ------------------------------------------------------
    def date_str(self) -> str:
        y, m = self.sim.next_date
        return f"year {y}, month {m}"

    def header(self):
        s = self.sim
        print(f"\n=== {self.city.name} | next month: {self.date_str()} | population {fmt(s.population)} ===")

    # -- screens -----------------------------------------------------
    def show_city(self):
        c = self.city
        print(f"\n{c.name}\n  Technology: {c.technology_level}\n  Geography:  {c.geography}\n  History:    {c.history}")
        print(f"  Resources/climate: {c.climate_and_resources}")
        print(f"  Initial population: {fmt(c.population)}   labour-force fraction: {c.labour_force_fraction:.0%}   unemployed share: {c.unemployed_share:.0%}")
        print("  Prototype limitation: no social actors, institutions, ideology or political organization are modelled;")
        print("  the economy runs in isolation.")
        for a in c.assumptions + self.spec.assumptions:
            print(f"  - {a}")

    def show_population(self):
        s, c = self.sim, self.city
        emp = s.population * c.labour_force_fraction * (1 - c.unemployed_share)
        print(f"\nPopulation: {fmt(s.population)} pops   employed labour: {fmt(emp)}")
        print(f"Monthly food requirement: {fmt(s.population)} units (1 per pop). Births 1%/yr, natural deaths 0.15%/yr.")
        print(f"Starvation record (last up to 3 months): {[round(h, 2) for h in s.demography.history]}")
        if s.last:
            r = s.last
            print(f"Last month: food {fmt(r.food_available)} / need {fmt(r.population_open)}, starving {fmt(r.starving)}, "
                  f"starvation deaths {fmt(r.starvation_deaths)}, births {fmt(r.births)}, natural deaths {fmt(r.natural_deaths)}")
        for g, per in self.spec.population_consumption.items():
            print(f"Also consumed per pop per month: {per} {self.goods[g].unit} of {self.goods[g].name}")

    def show_sectors(self):
        st = s.last.step.sector_status if (s := self.sim).last else {}
        print(f"\n{'Sector':<16}{'Labour':>9}{'Workers':>10}{'Util.':>7}  Limiting  | Capital / Inputs -> Outputs (per worker-month)")
        for sec in sorted(self.spec.sectors, key=lambda x: x.order):
            i = st.get(sec.id, {})
            lim = i.get("limiting") or "-"
            fmtd = lambda d: ", ".join(f"{k} {v:g}" for k, v in d.items()) or "-"
            print(f"{sec.name:<16}{sec.labour_share:>8.0%}{fmt(i.get('workers', 0)):>10}{i.get('utilization', 1):>7.0%}  {lim}")
            print(f"{'':<16}  capital: {fmtd(sec.capital)}\n{'':<16}  inputs:  {fmtd(sec.inputs)}\n{'':<16}  outputs: {fmtd(sec.outputs)}")

    def show_stocks(self):
        print(f"\n{'Good':<28}{'Kind':<14}{'Stock':>16}  Notes")
        for g in self.spec.goods:
            v = self.sim.economy.stocks[g.id]
            note = []
            if not g.stockable: note.append("not stored")
            if g.regen_per_month: note.append(f"regen {g.regen_per_month:,.0f}/mo")
            if g.depreciation_rate: note.append(f"wear {g.depreciation_rate:.2%}/mo")
            print(f"{g.name:<28}{g.kind:<14}{fmt(v):>16}  {', '.join(note)} [{g.unit}]")

    def show_flows(self):
        if not self.sim.last:
            print("\nNo month has been simulated yet."); return
        r = self.sim.last
        print(f"\nFlows in the last simulated month (year {r.year}, month {r.month}):")
        by: dict[str, dict[str, float]] = {}
        for f in r.step.ledger:
            by.setdefault(f.kind, {}); by[f.kind][f.good] = by[f.kind].get(f.good, 0) + f.amount
        for kind, d in by.items():
            print(f"  {kind}:")
            for g, v in sorted(d.items(), key=lambda kv: -abs(kv[1])):
                print(f"    {self.goods[g].name:<28}{v:>+16,.1f}")
        if r.step.shortfalls:
            print("  unmet population consumption:", {k: round(v, 1) for k, v in r.step.shortfalls.items()})

    def show_state(self):
        recs = self.sim.records
        if not recs:
            print("\nNo full year recorded yet. Current month count:", self.sim.months); return
        print(f"\n{'Year':>6}{'Pop start':>12}{'Pop end':>12}{'Births':>10}{'Nat.d.':>9}{'Starv.d.':>10}{'Food bal.':>12}{'Short mo.':>10}")
        for r in recs[-25:]:
            print(f"{r['year']:>6}{fmt(r['population_start']):>12}{fmt(r['population_end']):>12}{fmt(r['births']):>10}"
                  f"{fmt(r['natural_deaths']):>9}{fmt(r['starvation_deaths']):>10}{fmt(r['food_balance']):>12}{r['shortage_months']:>10}")
        if len(recs) > 25:
            print(f"  (showing the last 25 of {len(recs)} yearly records)")

    def show_conditions(self):
        s = self.sim
        print("\nConditions of material reproduction:")
        if not s.last:
            print("  No month simulated yet."); return
        r = s.last
        ratio = r.food_available / r.population_open if r.population_open else 0
        print(f"  Food coverage last month: {ratio:.1%} of requirement" + ("  <-- SHORTAGE" if ratio < 1 else ""))
        if s.demography.history:
            print(f"  Starvation record: {[round(h, 1) for h in s.demography.history]} (deaths follow after three consecutive months)")
        use: dict[str, float] = {}
        for f in r.step.ledger:
            if f.kind == "input_use":
                use[f.good] = use.get(f.good, 0) - f.amount
        threats = 0
        for sid, i in r.step.sector_status.items():
            if i["utilization"] < 0.999:
                threats += 1
                print(f"  Sector {self.names[sid]} at {i['utilization']:.0%}, limited by {i['limiting']}")
        for g in self.spec.goods:
            if g.kind == "reserve":
                net = use.get(g.id, 0) - g.regen_per_month
                stock = s.economy.stocks[g.id]
                if net > 0:
                    months = stock / net
                    threats += 1
                    print(f"  {g.name}: {fmt(stock)} left, net drain {fmt(net)}/month, about {months / 12:,.0f} years of cover")
        if not threats and ratio >= 1:
            print("  Nothing is currently limiting production.")

    def advance(self, months_label: str, results):
        if not results:
            return
        a, b = results[0], results[-1]
        print(f"  Processed {len(results)} month(s): {a.year}/{a.month} -> {b.year}/{b.month}. "
              f"Population {fmt(a.population_open)} -> {fmt(b.population_close)}.")
        sd = sum(r.starvation_deaths for r in results)
        short = sum(1 for r in results if r.starving > 0)
        if short:
            print(f"  {short} month(s) with a food shortage; starvation deaths in the period: {fmt(sd)}.")
        msg = self.sim.collapse_message()
        if msg:
            print("\n  " + msg)
            self.sim.save_history(self.path / "history.json")
            print(f"  Yearly history saved to {self.path / 'history.json'}. Press [r] for the final report.")

    def run(self):
        print(f"Loaded {self.city.name}. Horizon: {HORIZON_YEARS} years.")
        while True:
            self.header()
            print(MENU)
            k = read_key()
            ended = bool(self.sim.outcome)
            if k == "q":
                if self.sim.records:
                    self.sim.save_history(self.path / "history.json")
                return
            elif k == "n":
                if ended: print("  The simulation has ended."); continue
                self.advance("month", [self.sim.tick()])
            elif k == "y":
                if ended: print("  The simulation has ended."); continue
                try:
                    n = float(input("  Years to skip: "))
                except ValueError:
                    print("  Not a number."); continue
                self.advance("years", self.sim.skip_years(n))
            elif k == "1": self.show_city()
            elif k == "2": self.show_population()
            elif k == "3": self.show_sectors()
            elif k == "4": self.show_stocks()
            elif k == "5": self.show_flows()
            elif k == "6": self.show_state()
            elif k == "7": self.show_conditions()
            elif k == "r":
                if not ended: print("  The report is generated after the simulation ends."); continue
                from .report import write_report
                write_report(self.path, self.sim)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("city_dir")
    ap.add_argument("--run", type=int, metavar="YEARS", help="headless: run up to YEARS years and print the outcome")
    ap.add_argument("--report", action="store_true", help="with --run: also write the final report")
    a = ap.parse_args()
    app = App(Path(a.city_dir))
    if a.run:
        res = app.sim.skip_years(a.run)
        print(app.sim.collapse_message() or f"Stopped after {a.run} years; population {app.sim.population:,.0f}.")
        app.sim.save_history(app.path / "history.json")
        if a.report:
            from .report import write_report
            write_report(app.path, app.sim)
        return
    app.run()


if __name__ == "__main__":
    main()

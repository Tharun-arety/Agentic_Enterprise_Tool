from app.tools import loader  # noqa: F401
from app.evals.runner import run_offline
def main():
    cases=run_offline()
    for case in cases: print(f"{'PASS' if case.passed else 'FAIL'} {case.category}/{case.name}: {case.detail}")
    raise SystemExit(0 if all(x.passed for x in cases) else 1)
if __name__=="__main__": main()

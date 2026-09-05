"""Firebase glue around step.py: a clock, a button, and Firestore.

    paper_step   Cloud Scheduler, every 12 h. Steps both books if control/state
                 says running. This is the whole forward test once deployed.
    step_now     Callable from the page: "Run one step now". Owner only.

Books live at books/{chart,volmom} (see step.step for the document shape),
each fill under books/{name}/fills. The page can only read them; this
process is the only writer, through the admin SDK.
"""
import os
import time

from firebase_admin import firestore, initialize_app
from firebase_functions import https_fn, options, scheduler_fn

import step

initialize_app()
OWNER = os.environ.get("OWNER_EMAIL", "")
# 384 symbols x 2017 bars measured at 212 MB of data, plus the interpreter and
# the admin SDK; 512 MB was too close to the edge. ~7 min per step, so 30 min.
RUN = dict(timeout_sec=1800, memory=options.MemoryOption.GB_1)


def run(reason):
    db = firestore.client()
    state = db.document("control/state")
    # A step takes ~7 minutes, far longer than any browser will hold a call open,
    # so progress is reported here and the page watches this document instead.
    state.set({"stepping": True, "step_started": int(time.time() * 1000),
               "step_reason": reason}, merge=True)
    try:
        _run(db, reason)
    finally:
        # A killed instance never reaches this; the page ages the flag out.
        state.set({"stepping": False}, merge=True)


def _run(db, reason):
    bars, prices = step.market()
    now = int(time.time() * 1000)          # one stamp for both books, so curves line up
    for st in step.STRATEGIES:
        ref = db.document(f"books/{st['name']}")
        doc, fills = step.step(ref.get().to_dict(), st, bars, prices, now=now)
        ref.set({**doc, "reason": reason})
        for f in fills:
            ref.collection("fills").add(f)
        print(f"{st['title']} ({reason}): equity {doc['equity']:.2f}, "
              f"holding {', '.join(doc['picks']) or 'nothing'}")
    db.document("control/state").set({"last_step": now}, merge=True)


@scheduler_fn.on_schedule(schedule="every 12 hours", **RUN)
def paper_step(event: scheduler_fn.ScheduledEvent) -> None:
    state = firestore.client().document("control/state").get().to_dict() or {}
    if state.get("running"):
        run("schedule")


@https_fn.on_call(**RUN)
def step_now(req: https_fn.CallableRequest):
    if not OWNER or not req.auth or req.auth.token.get("email") != OWNER:
        raise https_fn.HttpsError(https_fn.FunctionsErrorCode.PERMISSION_DENIED, "owner only")
    run("manual")
    return {"ok": True}

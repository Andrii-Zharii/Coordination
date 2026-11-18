# -*- coding: utf-8 -*-
"""Start a zone session: snapshot of all MEP in the zone of the last clash check."""
from pyrevit import revit, forms, script

from coordination import session

doc = revit.doc
view = revit.active_view

pending = session.pending_session(doc)
if pending is not None:
    if not forms.alert(u"A zone session started at {} is not finished.\n\n"
                       u"Discard it and start a new one? (its start snapshot stays on disk)".format(pending["started"]),
                       yes=True, no=True):
        script.exit()
    session.discard_session()

try:
    zone, zone_text = session.zone_from_settings(doc, session.gc.load_settings())
except ValueError as error:
    forms.alert(u"{}".format(error), exitscript=True)

last = session.last_check(doc)
CHECK_NOW = u"Check clashes now (slower, exact)"
options = [CHECK_NOW]
use_last = None
if last is not None:
    use_last = u"Use the last check: {} clashes at {}".format(len(last.get("clashes") or []), last.get("created"))
    options.insert(0, use_last)
choice = forms.CommandSwitchWindow.show(
    options, message=u"Start a session in {}?\n(zone of the last 'Clash у зоні'; to change it, run the check first)".format(zone_text))
if not choice:
    script.exit()

clash_list = (last.get("clashes") or []) if choice == use_last else None
with forms.ProgressBar(title=u"Start: checking clashes... ({value} of {max_value})") as bar:
    state, count, clashes, image_ok = session.start_session(doc, view, bar.update_progress, clash_list)

message = u"Recorded {} MEP elements and {} clashes.".format(count, clashes)
if not image_ok:
    message += u"\nScreenshot failed."
forms.show_balloon(u"Start Zone", message + u"\nWork as usual, then press Finish Zone.")

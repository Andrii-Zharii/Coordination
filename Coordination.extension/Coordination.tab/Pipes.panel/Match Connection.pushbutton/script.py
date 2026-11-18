# -*- coding: utf-8 -*-
"""З'єднує дві нез'єднані труби так само, як з'єднання-зразок. Виділіть зразок (відвід, два відводи зміщення, трійник, врізку або перехід), потім клікайте пари труб біля кінців, які треба з'єднати. Esc — завершити."""
from pyrevit import revit, DB, forms, script
from Autodesk.Revit.UI.Selection import ISelectionFilter, ObjectType
from Autodesk.Revit.Exceptions import OperationCanceledException
from coordination.pipes import connect as C

doc = revit.doc
uidoc = revit.uidoc
output = script.get_output()


class _Filter(ISelectionFilter):
    def __init__(self, test):
        self.test = test

    def AllowElement(self, e):
        try:
            return self.test(e)
        except Exception:
            return False

    def AllowReference(self, ref, point):
        return False


def pick(test, prompt):
    """(element, picked point) or None on Esc."""
    try:
        ref = uidoc.Selection.PickObject(ObjectType.Element, _Filter(test), prompt)
    except OperationCanceledException:
        return None
    return doc.GetElement(ref.ElementId), ref.GlobalPoint


# 1. The sample connection.
ids = list(uidoc.Selection.GetElementIds())
if not ids:
    try:
        refs = uidoc.Selection.PickObjects(
            ObjectType.Element,
            _Filter(lambda e: C.is_fitting(e) or isinstance(e, DB.MEPCurve)),
            u"Виділіть з'єднання-зразок (фітинги, можна разом з трубою між ними) і натисніть Finish")
    except OperationCanceledException:
        script.exit()
    ids = [r.ElementId for r in refs]

try:
    sample = C.analyse_sample(doc, ids)
except C.ConnectError as ex:
    forms.alert(u"%s" % ex, exitscript=True)

if C.needs_main(sample):
    prompts = (u"Зразок: %s. Виберіть магістраль (Esc — завершити)" % sample["text"],
               u"Виберіть відгалуження біля кінця, який треба приєднати")
else:
    prompts = (u"Зразок: %s. Виберіть першу трубу біля кінця, який треба з'єднати (Esc — завершити)"
               % sample["text"],
               u"Виберіть другу трубу біля кінця, який треба з'єднати")

output.print_md(u"## Match Connection")
output.print_md(u"Зразок: **%s**" % sample["text"])

# 2. Pairs of target pipes, until Esc.
created = []
done = 0
failed = 0
while True:
    first = pick(C.is_straight_curve, prompts[0])
    if first is None:
        break
    second = pick(lambda e, f=first[0]: C.is_straight_curve(e) and e.Id != f.Id, prompts[1])
    if second is None:
        break
    names = u"%s ↔ %s" % (output.linkify(first[0].Id), output.linkify(second[0].Id))
    try:
        new_ids, notes = C.connect(doc, sample, first[0], first[1], second[0], second[1])
    except C.ConnectError as ex:
        failed += 1
        output.print_md(u"✖ %s: %s" % (names, ex))
        forms.alert(u"Не з'єднано, модель не змінено:\n%s" % ex)
        continue
    done += 1
    created.extend(new_ids)
    line = u"✔ %s: створено %s" % (names, output.linkify(new_ids))
    if notes:
        line += u" — " + u"; ".join(notes)
    output.print_md(line)

if created:
    revit.get_selection().set_to(created)
if done or failed:
    output.print_md(u"З'єднано пар: **%d**, не вдалося: **%d**." % (done, failed))

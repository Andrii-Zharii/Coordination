# -*- coding: utf-8 -*-
"""Re-copy a workset's elements on the active view from a link.

1. Delete: every model element of the host on the chosen workset (PL) that
   the active view shows.
2. Copy: every model element of the chosen link that the active view shows
   (Revit's own visibility: view range, crop box, visibility/graphics),
   pasted into the host on the same workset.

Not touched: annotations and other view-specific elements, links, imports,
rooms/areas, levels/grids.
"""
from pyrevit.api import DB
from System.Collections.Generic import List


def idv(element_id):
    value = getattr(element_id, "Value", None)
    return element_id.IntegerValue if value is None else value


def _is_model_element(e):
    if e is None or isinstance(e, DB.ElementType):
        return False
    if isinstance(e, (DB.RevitLinkInstance, DB.ImportInstance, DB.SpatialElement,
                      DB.Level, DB.Grid, DB.View)):
        return False
    if e.OwnerViewId != DB.ElementId.InvalidElementId:
        return False                    # annotation / view-specific
    cat = e.Category
    if cat is None or cat.CategoryType != DB.CategoryType.Model:
        return False
    if isinstance(e, DB.FamilyInstance) and e.SuperComponent is not None:
        return False                    # nested part: goes with its parent
    if isinstance(e, DB.MEPSystem):
        return False
    return e.get_BoundingBox(None) is not None


def host_elements_in_view(doc, view, workset):
    """Model elements of the host on `workset` shown in `view`: (deletable, borrowed)."""
    ok, borrowed = [], []
    for e in DB.FilteredElementCollector(doc, view.Id).WhereElementIsNotElementType():
        if e.WorksetId != workset.Id or not _is_model_element(e):
            continue
        try:
            other = DB.WorksharingUtils.GetCheckoutStatus(doc, e.Id) == DB.CheckoutStatus.OwnedByOtherUser
        except Exception:
            other = False
        (borrowed if other else ok).append(e.Id)
    return ok, borrowed


def link_elements_in_view(doc, view, link):
    """Ids (in the link document) of the link's model elements shown in `view`."""
    out = []
    for e in DB.FilteredElementCollector(doc, view.Id, link.Id).WhereElementIsNotElementType():
        if _is_model_element(e):
            out.append(e.Id)
    return out


def loaded_links(doc):
    """[(name, link instance)] of loaded links; the name is unique."""
    out = []
    seen = {}
    for li in DB.FilteredElementCollector(doc).OfClass(DB.RevitLinkInstance):
        ld = li.GetLinkDocument()
        if ld is None:
            continue
        name = ld.Title
        seen[name] = seen.get(name, 0) + 1
        if seen[name] > 1:
            name = u"%s (%d)" % (name, seen[name])
        out.append((name, li))
    return out


def user_worksets(doc):
    return list(DB.FilteredWorksetCollector(doc).OfKind(DB.WorksetKind.UserWorkset))


def workset_by_name(doc, name):
    for w in user_worksets(doc):
        if w.Name == name:
            return w
    return None


class _UseHostTypes(DB.IDuplicateTypeNamesHandler):
    def OnDuplicateTypeNamesFound(self, args):
        return DB.DuplicateTypeAction.UseDestinationTypes


class _Failures(DB.IFailuresPreprocessor):
    def __init__(self):
        self.errors = []

    def PreprocessFailures(self, fa):
        bad = False
        for f in fa.GetFailureMessages():
            if f.GetSeverity() == DB.FailureSeverity.Warning:
                fa.DeleteWarning(f)
            else:
                self.errors.append(f.GetDescriptionText())
                bad = True
        if bad:
            return DB.FailureProcessingResult.ProceedWithRollBack
        return DB.FailureProcessingResult.Continue


def _commit(t):
    fp = _Failures()
    o = t.GetFailureHandlingOptions()
    o.SetFailuresPreprocessor(fp)
    o.SetClearAfterRollback(True)
    t.SetFailureHandlingOptions(o)
    ok = t.Commit() == DB.TransactionStatus.Committed
    return ok, fp.errors


def run(doc, delete_ids, link, copy_ids, workset):
    """Delete, then copy, as one undo step. Returns (new ids, errors, step);
    on errors nothing is changed and `step` says which step failed."""
    table = doc.GetWorksetTable()
    old_active = table.GetActiveWorksetId()
    table.SetActiveWorksetId(workset.Id)
    group = DB.TransactionGroup(doc, "Copy from Link")
    group.Start()
    t = None
    try:
        if delete_ids:
            t = DB.Transaction(doc, "Delete old")
            t.Start()
            doc.Delete(List[DB.ElementId](delete_ids))
            ok, errors = _commit(t)
            if not ok:
                group.RollBack()
                return [], errors or [u"Revit не дав видалити"], u"видалення"
        new_ids = []
        if copy_ids:
            t = DB.Transaction(doc, "Copy from link")
            t.Start()
            opts = DB.CopyPasteOptions()
            opts.SetDuplicateTypeNamesHandler(_UseHostTypes())
            new_ids = list(DB.ElementTransformUtils.CopyElements(
                link.GetLinkDocument(), List[DB.ElementId](copy_ids), doc,
                link.GetTotalTransform(), opts))
            for i in new_ids:
                e = doc.GetElement(i)
                if e is None or e.WorksetId == workset.Id:
                    continue
                prm = e.get_Parameter(DB.BuiltInParameter.ELEM_PARTITION_PARAM)
                if prm is not None and not prm.IsReadOnly:
                    prm.Set(idv(workset.Id))
            ok, errors = _commit(t)
            if not ok:
                group.RollBack()
                return [], errors or [u"Revit не дав вставити"], u"вставка"
        group.Assimilate()
        return new_ids, [], None
    except Exception as ex:
        if t is not None and t.HasStarted() and not t.HasEnded():
            t.RollBack()
        if group.HasStarted() and not group.HasEnded():
            group.RollBack()
        return [], [u"%s" % ex], u"виконання"
    finally:
        try:
            table.SetActiveWorksetId(old_active)
        except Exception:
            pass

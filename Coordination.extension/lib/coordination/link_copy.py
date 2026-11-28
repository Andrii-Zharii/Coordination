# -*- coding: utf-8 -*-
"""Replace a workset's MEP on the active plan with a fresh copy from a link.

1. Band = the plan's view range: from the view depth (or bottom) to the top,
   inside the crop box when it is on.
2. Host elements on the chosen workset (PL) in the band are deleted.
3. Elements of the chosen link (PL) in the band are copied into the host,
   on the same workset.

"In the band" = the element's bounding box touches it, the same as what the
plan shows. Only MEP categories (see CATEGORIES) are deleted and copied.
"""
from pyrevit.api import DB
from System.Collections.Generic import List

from coordination.sections.floor import next_level_elevation

B = DB.BuiltInCategory
CATEGORIES = [
    B.OST_PipeCurves, B.OST_PipeFitting, B.OST_PipeAccessory, B.OST_FlexPipeCurves,
    B.OST_PipeInsulations, B.OST_PlumbingFixtures, B.OST_Sprinklers, B.OST_PlaceHolderPipes,
    B.OST_DuctCurves, B.OST_DuctFitting, B.OST_DuctAccessory, B.OST_FlexDuctCurves,
    B.OST_DuctInsulations, B.OST_DuctLinings, B.OST_DuctTerminal, B.OST_PlaceHolderDucts,
    B.OST_MechanicalEquipment,
    B.OST_CableTray, B.OST_CableTrayFitting, B.OST_Conduit, B.OST_ConduitFitting,
    B.OST_ElectricalEquipment, B.OST_ElectricalFixtures, B.OST_LightingFixtures,
]
FAR = 1.0e5          # feet: "no limit" in plan


def idv(element_id):
    value = getattr(element_id, "Value", None)
    return element_id.IntegerValue if value is None else value


# --- band of the view -----------------------------------------------------------

def _plane_z(doc, vr, plane):
    lid = vr.GetLevelId(plane)
    if lid is None or lid == DB.ElementId.InvalidElementId:
        return None
    if lid == DB.PlanViewRange.LevelAbove or lid == DB.PlanViewRange.Unlimited \
            or lid == DB.PlanViewRange.LevelBelow or lid == DB.PlanViewRange.Current:
        return None
    level = doc.GetElement(lid)
    if not isinstance(level, DB.Level):
        return None
    return level.ProjectElevation + vr.GetOffset(plane)


def view_band(doc, view):
    """(zmin, zmax, xy box or None) of the plan's view range, in host coordinates."""
    level = view.GenLevel
    vr = view.GetViewRange()
    top = _plane_z(doc, vr, DB.PlanViewPlane.TopClipPlane)
    bottom = _plane_z(doc, vr, DB.PlanViewPlane.ViewDepthPlane)
    if bottom is None:
        bottom = _plane_z(doc, vr, DB.PlanViewPlane.BottomClipPlane)
    if top is None:
        top = next_level_elevation(doc, level) or (level.ProjectElevation + 4000 / 304.8)
    if bottom is None:
        bottom = level.ProjectElevation
    xy = None
    if view.CropBoxActive:
        box = view.CropBox
        pts = [box.Transform.OfPoint(DB.XYZ(x, y, box.Min.Z))
               for x in (box.Min.X, box.Max.X) for y in (box.Min.Y, box.Max.Y)]
        xy = (min(p.X for p in pts), min(p.Y for p in pts),
              max(p.X for p in pts), max(p.Y for p in pts))
    return min(bottom, top), max(bottom, top), xy


def _outline(band, transform=None):
    """Outline of the band; with `transform` (host -> other model) in the other model's coordinates."""
    z0, z1, xy = band
    x0, y0, x1, y1 = xy if xy else (-FAR, -FAR, FAR, FAR)
    corners = [DB.XYZ(x, y, z) for x in (x0, x1) for y in (y0, y1) for z in (z0, z1)]
    if transform is not None:
        corners = [transform.OfPoint(p) for p in corners]
    return DB.Outline(DB.XYZ(min(p.X for p in corners), min(p.Y for p in corners), min(p.Z for p in corners)),
                      DB.XYZ(max(p.X for p in corners), max(p.Y for p in corners), max(p.Z for p in corners)))


def _collect(doc, outline):
    flt = DB.ElementMulticategoryFilter(List[B](CATEGORIES))
    out = []
    for e in (DB.FilteredElementCollector(doc).WherePasses(flt)
              .WherePasses(DB.BoundingBoxIntersectsFilter(outline))
              .WhereElementIsNotElementType()):
        if e.OwnerViewId != DB.ElementId.InvalidElementId:
            continue
        if isinstance(e, DB.FamilyInstance) and e.SuperComponent is not None:
            continue            # nested part: goes with its parent
        out.append(e)
    return out


def _sticks_out(e, band, transform=None):
    bb = e.get_BoundingBox(None)
    if bb is None:
        return False
    zs = [bb.Min.Z, bb.Max.Z]
    if transform is not None:
        zs = [transform.OfPoint(bb.Min).Z, transform.OfPoint(bb.Max).Z]
    return min(zs) < band[0] - 0.01 or max(zs) > band[1] + 0.01


# --- links and worksets ------------------------------------------------------------

def loaded_links(doc):
    """[(title, link instance)] of loaded links."""
    out = []
    for li in DB.FilteredElementCollector(doc).OfClass(DB.RevitLinkInstance):
        ld = li.GetLinkDocument()
        if ld is not None:
            out.append((ld.Title, li))
    return out


def user_worksets(doc):
    return list(DB.FilteredWorksetCollector(doc).OfKind(DB.WorksetKind.UserWorkset))


def workset_by_name(doc, name):
    for w in user_worksets(doc):
        if w.Name == name:
            return w
    return None


# --- plan and apply -----------------------------------------------------------------

def plan(doc, view, workset, link):
    """What will happen: dict with to_delete, borrowed, to_copy (link ids), link_doc,
    transform, band, sticking (elements reaching outside the band)."""
    band = view_band(doc, view)
    host = []
    borrowed = []
    for e in _collect(doc, _outline(band)):
        if e.WorksetId != workset.Id:
            continue
        try:
            other = DB.WorksharingUtils.GetCheckoutStatus(doc, e.Id) == DB.CheckoutStatus.OwnedByOtherUser
        except Exception:
            other = False
        (borrowed if other else host).append(e)
    tr = link.GetTotalTransform()
    ld = link.GetLinkDocument()
    linked = _collect(ld, _outline(band, tr.Inverse))
    sticking = sum(1 for e in linked if _sticks_out(e, band, tr))
    return {"band": band, "to_delete": [e.Id for e in host], "borrowed": [e.Id for e in borrowed],
            "to_copy": [e.Id for e in linked], "link_doc": ld, "transform": tr, "sticking": sticking}


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


def apply(doc, p, workset):
    """Delete and copy in one transaction. Returns (new ids, errors); on errors
    nothing is changed."""
    table = doc.GetWorksetTable()
    old_active = table.GetActiveWorksetId()
    table.SetActiveWorksetId(workset.Id)
    t = DB.Transaction(doc, "Replace from Link")
    try:
        t.Start()
        if p["to_delete"]:
            doc.Delete(List[DB.ElementId](p["to_delete"]))
        new_ids = []
        if p["to_copy"]:
            opts = DB.CopyPasteOptions()
            opts.SetDuplicateTypeNamesHandler(_UseHostTypes())
            new_ids = list(DB.ElementTransformUtils.CopyElements(
                p["link_doc"], List[DB.ElementId](p["to_copy"]), doc, p["transform"], opts))
        for i in new_ids:
            e = doc.GetElement(i)
            if e is None or e.WorksetId == workset.Id:
                continue
            prm = e.get_Parameter(DB.BuiltInParameter.ELEM_PARTITION_PARAM)
            if prm is not None and not prm.IsReadOnly:
                prm.Set(idv(workset.Id))
        fp = _Failures()
        o = t.GetFailureHandlingOptions()
        o.SetFailuresPreprocessor(fp)
        o.SetClearAfterRollback(True)
        t.SetFailureHandlingOptions(o)
        if t.Commit() != DB.TransactionStatus.Committed:
            return [], fp.errors or [u"Revit відхилив зміни"]
        return new_ids, []
    except Exception as ex:
        if t.HasStarted() and not t.HasEnded():
            t.RollBack()
        return [], [u"%s" % ex]
    finally:
        try:
            table.SetActiveWorksetId(old_active)
        except Exception:
            pass

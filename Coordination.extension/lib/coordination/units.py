# -*- coding: utf-8 -*-
"""Unit helpers. Revit's internal length unit is decimal feet."""

MM_PER_FOOT = 304.8


def ft_to_mm(value):
    return value * MM_PER_FOOT


def mm_to_ft(value):
    return value / MM_PER_FOOT

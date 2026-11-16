# -*- coding: utf-8 -*-
"""Voice notes: record the microphone to a WAV file with the Windows MCI API (winmm.dll).

Works from pyRevit's IronPython (ctypes). Recording runs in the background while a dialog
is open; closing the dialog stops it. The file is transcribed later in the cloud session
(tools/transcribe_cases.py), so any language works.
"""
import ctypes
import os
import shutil
import tempfile

_ALIAS = u"coordnote"


def _mci(command):
    buffer = ctypes.create_unicode_buffer(256)
    error = ctypes.windll.winmm.mciSendStringW(command, buffer, 255, 0)
    if error:
        text = ctypes.create_unicode_buffer(256)
        ctypes.windll.winmm.mciGetErrorStringW(error, text, 255)
        raise RuntimeError(u"Microphone error %d: %s (%s)" % (error, text.value, command))
    return buffer.value


def start():
    """Start recording from the default microphone (16 kHz, mono, 16 bit)."""
    try:
        _mci(u"close %s" % _ALIAS)
    except RuntimeError:
        pass
    _mci(u"open new type waveaudio alias %s" % _ALIAS)
    _mci(u"set %s bitspersample 16 samplespersec 16000 channels 1 bytespersec 32000 alignment 2" % _ALIAS)
    _mci(u"record %s" % _ALIAS)


def stop(target_path):
    """Stop recording and save the WAV to target_path. Returns the size in bytes."""
    temp_path = os.path.join(tempfile.gettempdir(), u"coordination_note.wav")
    try:
        _mci(u"stop %s" % _ALIAS)
        if os.path.isfile(temp_path):
            os.remove(temp_path)
        _mci(u'save %s "%s"' % (_ALIAS, temp_path))
    finally:
        try:
            _mci(u"close %s" % _ALIAS)
        except RuntimeError:
            pass
    if os.path.isfile(target_path):
        os.remove(target_path)
    shutil.move(temp_path, target_path)
    return os.path.getsize(target_path)


def cancel():
    try:
        _mci(u"stop %s" % _ALIAS)
    except RuntimeError:
        pass
    try:
        _mci(u"close %s" % _ALIAS)
    except RuntimeError:
        pass

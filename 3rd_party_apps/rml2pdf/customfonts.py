# -*- coding: utf-8 -*-
##############################################################################
#
#    OpenERP, Open Source Management Solution
#    Copyright (C) 2004-2009 P. Christeas, Tiny SPRL (<http://tiny.be>).
#    Copyright (C) 2010 OpenERP SA. (http://www.openerp.com)
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU Affero General Public License as
#    published by the Free Software Foundation, either version 3 of the
#    License, or (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU Affero General Public License for more details.
#
#    You should have received a copy of the GNU Affero General Public License
#    along with this program.  If not, see <http://www.gnu.org/licenses/>.     
#
##############################################################################

import glob
import os, sys
import logging
import platform

from reportlab import rl_config
try:
    from main.conf import settings
except ImportError:
    settings = {}

if True:
    class config(object):
        @staticmethod
        def get_misc(k, k2, default):
            if settings and k in settings:
                return settings[k].get(k2, default)
            else:
                return default


#.apidoc title: TTF Font Table

"""This module allows the mapping of some system-available TTF fonts to
the reportlab engine.

This file could be customized per distro (although most Linux/Unix ones)
should have the same filenames, only need the code below).

Due to an awful configuration that ships with reportlab at many Linux 
and Ubuntu distros, we have to override the search path, too.
"""

CustomTTFonts = [ ('Helvetica',"DejaVu Sans", "DejaVuSans.ttf", 'normal'),
        ('Helvetica',"DejaVu Sans Bold", "DejaVuSans-Bold.ttf", 'bold'),
        ('Helvetica',"DejaVu Sans Oblique", "DejaVuSans-Oblique.ttf", 'italic'),
        ('Helvetica',"DejaVu Sans BoldOblique", "DejaVuSans-BoldOblique.ttf", 'bolditalic'),
        ('Times',"Liberation Serif", "LiberationSerif-Regular.ttf", 'normal'),
        ('Times',"Liberation Serif Bold", "LiberationSerif-Bold.ttf", 'bold'),
        ('Times',"Liberation Serif Italic", "LiberationSerif-Italic.ttf", 'italic'),
        ('Times',"Liberation Serif BoldItalic", "LiberationSerif-BoldItalic.ttf", 'bolditalic'),
        ('Times-Roman',"Liberation Serif", "LiberationSerif-Regular.ttf", 'normal'),
        ('Times-Roman',"Liberation Serif Bold", "LiberationSerif-Bold.ttf", 'bold'),
        ('Times-Roman',"Liberation Serif Italic", "LiberationSerif-Italic.ttf", 'italic'),
        ('Times-Roman',"Liberation Serif BoldItalic", "LiberationSerif-BoldItalic.ttf", 'bolditalic'),
        ('ZapfDingbats',"DejaVu Serif", "DejaVuSerif.ttf", 'normal'),
        ('ZapfDingbats',"DejaVu Serif Bold", "DejaVuSerif-Bold.ttf", 'bold'),
        ('ZapfDingbats',"DejaVu Serif Italic", "DejaVuSerif-Italic.ttf", 'italic'),
        ('ZapfDingbats',"DejaVu Serif BoldItalic", "DejaVuSerif-BoldItalic.ttf", 'bolditalic'),
        ('Courier',"FreeMono", "FreeMono.ttf", 'normal'),
        ('Courier',"FreeMono Bold", "FreeMonoBold.ttf", 'bold'),
        ('Courier',"FreeMono Oblique", "FreeMonoOblique.ttf", 'italic'),
        ('Courier',"FreeMono BoldOblique", "FreeMonoBoldOblique.ttf", 'bolditalic'),]


TTFSearchPath_Linux = [
            '/usr/share/fonts/truetype', # SuSE
            '/usr/share/fonts/dejavu', '/usr/share/fonts/liberation', # Fedora, RHEL
            '/usr/share/fonts/truetype/*', # Ubuntu,
            '/usr/share/fonts/TTF/*', # at Mandriva/Mageia
            ]

TTFSearchPath_Windows = [
            'c:/winnt/fonts',
            'c:/windows/fonts'
            ]

TTFSearchPath_Darwin = [
            #mac os X - from
            #http://developer.apple.com/technotes/tn/tn2024.html
            '~/Library/Fonts',
            '/Library/Fonts',
            '/Network/Library/Fonts',
            '/System/Library/Fonts',
            ]

TTFSearchPathMap = {
    'Darwin': TTFSearchPath_Darwin,
    'Windows': TTFSearchPath_Windows,
    'Linux': TTFSearchPath_Linux,
}

# ----- The code below is less distro-specific, please avoid editing! -------
__foundFonts = None

def FindCustomFonts():
    """Fill the __foundFonts list with those filenames, whose fonts
       can be found in the reportlab ttf font path.
       
       This process needs only be done once per loading of this module,
       it is cached. But, if the system admin adds some font in the
       meanwhile, the server must be restarted eventually.
    """
    dirpath =  []
    log = logging.getLogger('report.fonts')
    global __foundFonts
    searchpath = []
    __foundFonts = {}

    if config.get_misc('ttfonts', 'search_path', False):
        searchpath += map(str.strip, config.get_misc('ttfonts', 'search_path').split(','))

    local_plat = platform.system()
    searchpath += TTFSearchPathMap.get(local_plat, [])
    
    if config.get_misc('ttfonts', 'use_default_path', True):
        # Append the original search path of reportlab (at the end)
        searchpath += rl_config.TTFSearchPath

    for dirglob in searchpath:
        dirglob = os.path.expanduser(dirglob)
        for dirname in glob.iglob(dirglob):
            abp = os.path.abspath(dirname)
            if os.path.isdir(abp):
                dirpath.append(abp)
        
    for name, font, fname, mode in CustomTTFonts:
        if fname in __foundFonts:
            continue
        for d in dirpath:
            afn = os.path.join(d, fname)
            if os.path.exists(afn):
                log.debug("Found font %s at %s", fname, afn)
                __foundFonts[fname] = afn
                break
        else:
            log.debug("Not found font for %s: %s", name, font)

    # print "Found fonts:", __foundFonts


def SetCustomFonts(rmldoc):
    """ Map some font names to the corresponding TTF fonts
    
        The ttf font may not even have the same name, as in
        Times -> Liberation Serif.
        This function is called once per report, so it should
        avoid system-wide processing (cache it, instead).
    """
    global __foundFonts
    if __foundFonts is None:
        FindCustomFonts()
    for name, font, fname, mode in CustomTTFonts:
        if os.path.isabs(fname) and os.path.exists(fname):
            rmldoc.setTTFontMapping(name, font, fname, mode)
        elif fname in __foundFonts:
            rmldoc.setTTFontMapping(name, font, __foundFonts[fname], mode)
    return True

#eof
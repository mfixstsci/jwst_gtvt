#! /usr/bin/env python

"""Get target information for target visibility tool. This script creates the tables
and plots that show a target visibility with JWST. This can be done for fixed or moving targets.

Usage:
  jwst_tvt fixed <ra> <dec> <targname> [--start_date=<t0>] [--end_date=<t_end>] [--instrument=<inst>] [--save_table=<st>] [--save_plot=<sp>] [--v3pa=<pa>]
  jwst_tvt moving <targname> [--start_date=<t0>] [--end_date=<t_end>] [--instrument=<inst>] [--save_table=<st>] [--save_plot=<sp>] [--v3pa=<pa>]
  
Arguments:
  <targname>             Name of target
  
Options:
  -h --help              Show this screen.
  --version              Show version.
  --start_date=<t0>      Start time of observation [default: 2020-01-01]
  --end_date=<t_end>     End time of observation [default: 2024-01-01]
  --instrument=<inst>    If specified plot shows only windows for this instrument.  Options: nircam, nirspec, niriss, miri, fgs, v3 (case insensitive).
  --save_table=<st>      Path of file to save table output.
  --save_plot=<sp>       Path of file to save plot output.
"""

from __future__ import print_function

import sys
import math
from . import ephemeris_old2x as EPH
import argparse
from astroquery.jplhorizons import Horizons
from docopt import docopt
import warnings
import matplotlib.pyplot as plt
from matplotlib.dates import YearLocator, MonthLocator, DateFormatter
from astropy.time import Time
from astropy.table import Table
import numpy as np
from os.path import join, abspath, dirname

# ignore astropy warning that Date after 2020-12-30 is "dubious"
warnings.filterwarnings('ignore', category=UserWarning, append=True)
warnings.filterwarnings('ignore', category=RuntimeWarning, append=True)

D2R = math.pi / 180.  #degrees to radians
R2D = 180. / math.pi #radians to degrees 
PI2 = 2. * math.pi   # 2 pi
unit_limit = lambda x: min(max(-1.,x),1.) # forces value to be in [-1,1]

def convert_ddmmss_to_float(astring):
    # Maybe look into astropy.coordinates for conversion.
    aline = astring.split(':')
    d= float(aline[0])
    m= float(aline[1])
    s= float(aline[2])
    hour_or_deg = (s/60.+m)/60.+d
    return hour_or_deg

def bound_angle(ang):
    while ang<0.:
        ang += 360.
    while ang>360.:
        ang -= 360.
    return ang

def angular_sep(obj1_c1,obj1_c2,obj2_c1,obj2_c2):
    """angular distance betrween two objects, positions specified in spherical coordinates."""
    x = math.cos(obj2_c2)*math.cos(obj1_c2)*math.cos(obj2_c1-obj1_c1) + math.sin(obj2_c2)*math.sin(obj1_c2)
    return math.acos(unit_limit(x))

def calc_ecliptic_lat(ra, dec):
    NEP_ra = 270.000000 * D2R
    NEP_dec = 66.560708 * D2R
    a_sep = angular_sep(ra, dec, NEP_ra, NEP_dec)
    ecl_lat = math.pi/2. - a_sep
    return ecl_lat

def sun_pitch(aV):
    return math.atan2(aV.x,-aV.z)

def sun_roll(aV):
    return math.asin(-aV.y)

def allowed_max_sun_roll(sun_p):
    abs_max_sun_roll = 5.2 *D2R
    if sun_p > 2.5*D2R:
        max_sun_roll = abs_max_sun_roll - 1.7*D2R * (sun_p - 2.5*D2R)/(5.2 - 2.5)/D2R
    else:
        max_sun_roll = abs_max_sun_roll
    max_sun_roll -= 0.1*D2R  #Pad away from the edge
    return max_sun_roll

def allowed_max_vehicle_roll(sun_ra, sun_dec, ra, dec):
    vehicle_pitch = math.pi/2. - angular_sep(sun_ra, sun_dec, ra, dec)
    sun_roll = 5.2 * D2R
    last_sun_roll = 0.
    while abs(sun_roll - last_sun_roll) > 0.0001*D2R:
        last_sun_roll = sun_roll
        sun_pitch = math.asin(unit_limit(math.sin(vehicle_pitch)/math.cos(last_sun_roll)))
        sun_roll = allowed_max_sun_roll(sun_pitch)
        #print sun_roll*R2D,sun_pitch*R2D,vehicle_pitch*R2D
    max_vehicle_roll = math.asin(unit_limit(math.sin(sun_roll)/math.cos(vehicle_pitch)))
    return max_vehicle_roll

def get_target_ephemeris(desg, start_date, end_date):
    """Ephemeris from JPL/HORIZONS.

    smallbody : bool, optional
      Set to `True` for comets and asteroids, `False` for planets,
      spacecraft, or moons.

    Returns : target name from HORIZONS, RA, and Dec.

    """

    obj = Horizons(id=desg, location='500@-170', smallbody=True,
                   epochs={'start':start_date, 'stop':end_date,
                   'step':'1d'})
    
    eph = obj.ephemerides()

    return eph['targetname'][0], eph['RA'], eph['DEC']
        

def window_summary_line(fixed, wstart, wend, pa_start, pa_end, ra_start, ra_end, dec_start, dec_end, cvz=False):
    """Formats window summary data for fixed and moving targets."""
    if cvz:
        line = " {0:15} {0:11} {0:11} ".format('CVZ')
    else:
        line = " {:15} {:11} {:11.2f} ".format(Time(wstart, format='mjd', out_subfmt='date').isot,
                                               Time(wend, format='mjd', out_subfmt='date').isot,wend-wstart)
    line += "{:13.5f} {:13.5f} ".format(pa_start*R2D,pa_end*R2D)
    if fixed:
        line += "{:13.5f} {:13.5f} ".format(ra_start*R2D, dec_start*R2D)
    else:
        line += "{:13.5f} {:13.5f} {:13.5f} {:13.5f} ".format(ra_start*R2D, ra_end*R2D, dec_start*R2D, dec_end*R2D)

    return line

def main():

    args = docopt(__doc__, version='0.1')
    
    table_output=None
    if args['--save_table'] is not None:
        table_output = open(args['--save_table'], 'w')
        
    NRCALL_FULL_V2IdlYang = -0.0265
    NRS_FULL_MSA_V3IdlYang = 137.4874
    NIS_V3IdlYang = -0.57
    MIRIM_FULL_V3IdlYang = 5.0152
    FGS1_FULL_V3IdlYang = -1.2508
    
    A_eph = EPH.Ephemeris(args['--start_date'], args['--end_date'])

    search_start = Time(args['--start_date'], format='iso').mjd if args['--start_date'] is not None else 58849.0  #Jan 1, 2020
    search_end = Time(args['--end_date'], format='iso').mjd if args['--end_date'] is not None else 60675.0 # Dec 31, 2024

    if not (58849.0 <= search_start <= 60675.0) and args['--start_date'] is not None:
        raise ValueError('Start date {} outside of available ephemeris {} to {}'.format(args['--start_date'], '2020-01-01', '2024-12-31'))
    if not (58849.0 <= search_end <= 60675.0) and args['--end_date'] is not None:
        raise ValueError('End date {} outside of available ephemeris {} to {}'.format(args['--end_date'], '2020-01-01', '2024-12-31'))
    if search_start > search_end:
        raise ValueError('Start date {} should be before end date {}'.format(args['--start_date'], args['--end_date']))

    if search_start < A_eph.amin:
        print("Warning, search start time is earlier than ephemeris start.", file=table_output)
        search_start = A_eph.amin + 1

    scale = 1  # Channging this value must be reflected in get_target_ephemeris
    span = int(search_end-search_start)

    pa = 'X'

    if args['fixed']:
        name = args['<targname>']
        # convert hh:mm:ss.s or dd:mm:ss.s to decimal  
        if ':' in args['<ra>']:
            ra  = convert_ddmmss_to_float(args['<ra>']) * 15. * D2R
            dec = convert_ddmmss_to_float(args['<dec>']) * D2R
        else:
            # else, already in decimal format
            ra  = float(args['<ra>']) * D2R
            dec = float(args['<dec>']) * D2R

        # although the coordinates are fixed, we need an array for
        # symmetry with moving target ephemerides
        ra = np.repeat(ra, span * scale + 1)
        dec = np.repeat(dec, span * scale + 1)
    
    elif args['moving']:
        name, ra, dec = get_target_ephemeris(args['<targname>'], args['--start_date'], args['--end_date'])
        # Why? Need to check assertion.
        assert len(ra) == span * scale + 1, "{} epochs retrieved for the moving target, but {} expected.".format(len(ra), span * scale + 1)
        ra = ra * D2R
        dec = dec * D2R

    print("", file=table_output)
    print("       Target", file=table_output)
    if args['fixed']:
        print("                ecliptic", file=table_output)
        print("RA      Dec     latitude", file=table_output)
        print("%7.3f %7.3f %7.3f" % (ra[0]*R2D,dec[0]*R2D,calc_ecliptic_lat(ra[0], dec[0])*R2D), file=table_output)
    print("", file=table_output)


    if args['--v3pa'] is not None:
        pa = float(args['--v3pa']) * D2R
    
    print("Checked interval [{}, {}]".format(Time(search_start, format='mjd', out_subfmt='date').isot, 
        Time(search_start+span, format='mjd', out_subfmt='date').isot), file=table_output)
    
    if pa == "X":
        iflag_old = A_eph.in_FOR(search_start,ra[0],dec[0])
        print("|           Window [days]                 |    Normal V3 PA [deg]    |", end='', file=table_output)
    else:
        iflag_old = A_eph.is_valid(search_start,ra[0],dec[0],pa)
        print("|           Window [days]                 |   Specified V3 PA [deg]  |", end='', file=table_output)

    if args['fixed']:
        print('\n', end='', file=table_output)
    else:
        print('{:^27s}|{:^27s}|'.format('RA', 'Dec'), file=table_output)

    print("   Start           End         Duration         Start         End    ", end='', file=table_output)
    
    if args['fixed']:
        print("{:^13s} {:^13s}".format('RA', 'Dec'), file=table_output)
    else:
        print("{:^13s} {:^13s} {:^13s} {:^13s}".format('Start', 'End', 'Start', 'End'), file=table_output)

    # Why?
    if iflag_old:
      twstart = search_start
      ra_start = ra[0]
      dec_start = dec[0]
    else:
      twstart = -1.
    iflip = False

    ####################### Start Block 1 #######################

    # i = time step. span = end_date - start_date

    # Step througth the **time** interval and find where target goes in/out of field of regard.
    for i in range(0,span*scale):
        adate = search_start + float(i)/float(scale)

        # pa = pitch angle
        if pa == "X":
            iflag = A_eph.in_FOR(adate,ra[i],dec[i])
        else:
            iflag = A_eph.is_valid(adate,ra[i],dec[i],pa)
        
        if iflag != iflag_old:
            iflip = True    
            if iflag:
                if pa == "X":
                    twstart = A_eph.bisect_by_FOR(adate,adate-0.1,ra[i],dec[i])
                else:
                    twstart = A_eph.bisect_by_attitude(adate,adate-0.1,ra[i],dec[i],pa)
                ra_start = ra[i]
                dec_start = dec[i]
            else:
                if pa == "X":
                    wend = A_eph.bisect_by_FOR(adate-0.1,adate,ra[i],dec[i])
                else:
                    wend = A_eph.bisect_by_attitude(adate-0.1,adate,ra[i],dec[i],pa)
                
                if twstart > 0.:
                    wstart = twstart # Only set wstart if wend is valid
                    if pa == "X":
                        pa_start = A_eph.normal_pa(wstart,ra_start,dec_start)
                        pa_end   = A_eph.normal_pa(wend,ra[i],dec[i])
                    else:
                        pa_start = pa
                        pa_end = pa
                    
                    ra_end = ra[i]
                    dec_end = dec[i]
                    
                    print(window_summary_line(args['fixed'], wstart, wend, pa_start, pa_end, ra_start, ra_end, dec_start, dec_end), file=table_output)
            
            iflag_old = iflag
        
    ####################### End Block 1 #######################

    if iflip == True and iflag == True:
        if pa == "X":
            pa_start = A_eph.normal_pa(twstart,ra[i],dec[i])
            pa_end   = A_eph.normal_pa(adate,ra[i],dec[i])
        else:
            pa_start = pa
            pa_end = pa
        
        print(window_summary_line(args['fixed'], twstart, adate, pa_start, pa_end, ra[i], ra[i], dec[i], dec[i]), file=table_output)

    if iflip == False and iflag == True and pa == "X":
        if dec[i] >0.:
            print(window_summary_line(args['fixed'], 0, 0, 2 * np.pi, 0, ra[0], ra[-1], dec[0], dec[-1], cvz=True), file=table_output)
        else:
            print(window_summary_line(args['fixed'], 0, 0, 0, 2 * np.pi, ra[0], ra[-1], dec[0], dec[-1], cvz=True), file=table_output)

    if 1==1:
        wstart = search_start
        wend = wstart + span
        istart = int(wstart)
        iend = int(wend)
        iflag = A_eph.in_FOR(wstart,ra[0],dec[0])
        tgt_is_in = False
        if iflag:
          tgt_is_in = True

        print("", file=table_output)
        print("", file=table_output)
        if args['fixed']:
            fmt_repeats = 6
            print("                V3PA          NIRCam           NIRSpec         NIRISS           MIRI          FGS", file=table_output)
            print("   Date      min    max      min    max       min    max     min    max      min    max      min    max", file=table_output)
                  #58849.0 264.83 275.18 264.80 264.80  42.32  42.32 264.26 264.26 269.84 269.84 263.58 263.58
        else:
            fmt_repeats = 7
            print("                                V3PA          NIRCam           NIRSpec         NIRISS           MIRI          FGS", file=table_output)
            print("   Date      RA     Dec      min    max      min    max       min    max     min    max      min    max      min    max", file=table_output)
        times = []
        minV3PA_data = []
        maxV3PA_data = []
        minNIRCam_PA_data = []
        maxNIRCam_PA_data = []
        minNIRSpec_PA_data = [] 
        maxNIRSpec_PA_data = []
        minNIRISS_PA_data = []
        maxNIRISS_PA_data = []
        minMIRI_PA_data = []
        maxMIRI_PA_data = []
        minFGS_PA_data = []
        maxFGS_PA_data = []

        for itime in range(istart,iend):
            atime = float(itime)
            i = int((atime - search_start) * float(scale))
            iflag = A_eph.in_FOR(atime,ra[i],dec[i])
            #print atime,A_eph.in_FOR(atime,ra,dec)
            if iflag:
                if not tgt_is_in:
                    print("", file=table_output)
                tgt_is_in = True
                
                V3PA = A_eph.normal_pa(atime,ra[i],dec[i])*R2D
                (sun_ra, sun_dec) = A_eph.sun_pos(atime)
                max_boresight_roll = allowed_max_vehicle_roll(sun_ra, sun_dec, ra[i], dec[i]) * R2D
                #sun_ang = angular_sep(sun_ra, sun_dec, ra, dec) * R2D
                
                minV3PA = bound_angle(V3PA - max_boresight_roll)
                maxV3PA = bound_angle(V3PA + max_boresight_roll)
                minNIRCam_PA = bound_angle(V3PA - max_boresight_roll + NRCALL_FULL_V2IdlYang)
                maxNIRCam_PA = bound_angle(V3PA + max_boresight_roll + NRCALL_FULL_V2IdlYang)
                minNIRSpec_PA = bound_angle(V3PA - max_boresight_roll + NRS_FULL_MSA_V3IdlYang)
                maxNIRSpec_PA = bound_angle(V3PA + max_boresight_roll + NRS_FULL_MSA_V3IdlYang)
                minNIRISS_PA = bound_angle(V3PA - max_boresight_roll + NIS_V3IdlYang)
                maxNIRISS_PA = bound_angle(V3PA + max_boresight_roll + NIS_V3IdlYang)
                minMIRI_PA = bound_angle(V3PA - max_boresight_roll + MIRIM_FULL_V3IdlYang)
                maxMIRI_PA = bound_angle(V3PA + max_boresight_roll + MIRIM_FULL_V3IdlYang)
                minFGS_PA = bound_angle(V3PA - max_boresight_roll + FGS1_FULL_V3IdlYang)
                maxFGS_PA = bound_angle(V3PA + max_boresight_roll + FGS1_FULL_V3IdlYang)

                times.append(Time(atime, format='mjd').datetime)
                minV3PA_data.append(minV3PA)
                maxV3PA_data.append(maxV3PA)
                minNIRCam_PA_data.append(minNIRCam_PA)
                maxNIRCam_PA_data.append(maxNIRCam_PA)
                minNIRSpec_PA_data.append(minNIRSpec_PA) 
                maxNIRSpec_PA_data.append(maxNIRSpec_PA)
                minNIRISS_PA_data.append(minNIRISS_PA)
                maxNIRISS_PA_data.append(maxNIRISS_PA)
                minMIRI_PA_data.append(minMIRI_PA)
                maxMIRI_PA_data.append(maxMIRI_PA)
                minFGS_PA_data.append(minFGS_PA)
                maxFGS_PA_data.append(maxFGS_PA)            
                #print '%7.1f %6.2f %6.2f %6.2f' % (atime, V3PA, NIRCam_PA, NIRSpec_PA)
                fmt = '{}' + '   {:6.2f} {:6.2f}'*fmt_repeats
                if args['fixed']:
                    print(fmt.format(
                        Time(atime, format='mjd', out_subfmt='date').isot, minV3PA, maxV3PA,
                        minNIRCam_PA, maxNIRCam_PA, minNIRSpec_PA, maxNIRSpec_PA, minNIRISS_PA,
                        maxNIRISS_PA, minMIRI_PA, maxMIRI_PA, minFGS_PA, maxFGS_PA), file=table_output)#,sun_ang
                else:
                    print(fmt.format(
                        Time(atime, format='mjd', out_subfmt='date').isot, ra[i]*R2D, dec[i]*R2D, minV3PA, maxV3PA,
                        minNIRCam_PA, maxNIRCam_PA, minNIRSpec_PA, maxNIRSpec_PA, minNIRISS_PA,
                        maxNIRISS_PA, minMIRI_PA, maxMIRI_PA, minFGS_PA, maxFGS_PA), file=table_output)#,sun_ang
            else:
                tgt_is_in = False
                times.append(Time(atime, format='mjd').datetime)
                minV3PA_data.append(np.nan)
                maxV3PA_data.append(np.nan)
                minNIRCam_PA_data.append(np.nan)
                maxNIRCam_PA_data.append(np.nan)
                minNIRSpec_PA_data.append(np.nan) 
                maxNIRSpec_PA_data.append(np.nan)
                minNIRISS_PA_data.append(np.nan)
                maxNIRISS_PA_data.append(np.nan)
                minMIRI_PA_data.append(np.nan)
                maxMIRI_PA_data.append(np.nan)
                minFGS_PA_data.append(np.nan)
                maxFGS_PA_data.append(np.nan)

        tab = Table([times, minV3PA_data, maxV3PA_data, minNIRCam_PA_data, maxNIRCam_PA_data, 
            minNIRSpec_PA_data, maxNIRSpec_PA_data, minNIRISS_PA_data, maxNIRISS_PA_data, 
            minMIRI_PA_data, maxMIRI_PA_data, minFGS_PA_data, maxFGS_PA_data], 
            names=('Date', 'V3PA min', 'V3PA max', 'NIRCam min', 'NIRCam max', 
                'NIRSpec min', 'NIRSpec max', 'NIRISS min', 'NIRISS max', 
                'MIRI min', 'MIRI max', 'FGS min', 'FGS max'))

        # Plot observing windows
        if args['--instrument'] is None:
            years = YearLocator()
            months = MonthLocator()
            yearsFmt = DateFormatter('%Y')
            monthsFmt = DateFormatter('%m')
            fig, axes = plt.subplots(2, 3, figsize=(14,8))

            axes[0,0].set_title("V3")
            plot_single_instrument(axes[0,0], "V3", times, minV3PA_data, maxV3PA_data)
            axes[0,0].fmt_xdata = DateFormatter('%Y-%m-%d')
            axes[0,0].set_ylabel("Available Position Angle (Degree)")
            axes[0,0].set_xlim(Time(search_start, format='mjd').datetime, Time(search_end, format='mjd').datetime)
            labels = axes[0,0].get_xticklabels()
            for label in labels:
                label.set_rotation(30)

            if args['fixed']:
                axes[0,1].set_title('(R.A. = {}, Dec. = {})\n'.format(args['<ra>'], args['<dec>'])+"NIRCam")
            plot_single_instrument(axes[0,1], 'NIRCam', times, minNIRCam_PA_data, maxNIRCam_PA_data)
            axes[0,1].fmt_xdata = DateFormatter('%Y-%m-%d')
            axes[0,1].set_ylabel("Available Position Angle (Degree)")
            axes[0,1].set_xlim(Time(search_start, format='mjd').datetime, Time(search_end, format='mjd').datetime)
            labels = axes[0,1].get_xticklabels()
            for label in labels:
                label.set_rotation(30)

            axes[0,2].set_title("MIRI")
            plot_single_instrument(axes[0,2], 'MIRI', times, minMIRI_PA_data, maxMIRI_PA_data)
            axes[0,2].set_xlim(Time(search_start, format='mjd').datetime, Time(search_end, format='mjd').datetime)
            labels = axes[0,2].get_xticklabels()
            for label in labels:
                label.set_rotation(30)

            axes[1,0].set_title("NIRSpec")
            axes[1,0].fmt_xdata = DateFormatter('%Y-%m-%d')
            plot_single_instrument(axes[1,0], 'NIRSpec', times, minNIRSpec_PA_data, maxNIRSpec_PA_data)
            axes[1,0].set_xlim(Time(search_start, format='mjd').datetime, Time(search_end, format='mjd').datetime)
            labels = axes[1,0].get_xticklabels()
            for label in labels:
                label.set_rotation(30)

            axes[1,1].set_title("NIRISS")
            plot_single_instrument(axes[1,1], 'NIRISS', times, minNIRISS_PA_data, maxNIRISS_PA_data)
            axes[1,1].set_xlim(Time(search_start, format='mjd').datetime, Time(search_end, format='mjd').datetime)
            labels = axes[1,1].get_xticklabels()
            for label in labels:
                label.set_rotation(30)

            axes[1,2].set_title("FGS")
            plot_single_instrument(axes[1,2], 'FGS', times, minFGS_PA_data, maxFGS_PA_data)
            axes[1,2].set_xlim(Time(search_start, format='mjd').datetime, Time(search_end, format='mjd').datetime)
            labels = axes[1,2].get_xticklabels()
            for label in labels:
                label.set_rotation(30)
            # fig.autofmt_xdate()

        elif args['--instrument'].lower() not in ['v3', 'nircam', 'miri', 'nirspec', 'niriss', 'fgs']:
            print()
            print(args['--instrument']+" not recognized. --instrument should be one of: v3, nircam, miri, nirspec, niriss, fgs")
            return

        elif args['--instrument'].lower() == 'v3':
            fig, ax = plt.subplots(figsize=(14,8))
            plot_single_instrument(ax, 'Observatory V3', times, minV3PA_data, maxV3PA_data)
            ax.set_xlim(Time(search_start, format='mjd').datetime, Time(search_end, format='mjd').datetime)

        elif args['--instrument'].lower() == 'nircam':
            fig, ax = plt.subplots(figsize=(14,8))
            plot_single_instrument(ax, 'NIRCam', times, minNIRCam_PA_data, maxNIRCam_PA_data)
            ax.set_xlim(Time(search_start, format='mjd').datetime, Time(search_end, format='mjd').datetime)

        elif args['--instrument'].lower() == 'miri':
            fig, ax = plt.subplots(figsize=(14,8))
            plot_single_instrument(ax, 'MIRI', times, minMIRI_PA_data, maxMIRI_PA_data)
            ax.set_xlim(Time(search_start, format='mjd').datetime, Time(search_end, format='mjd').datetime)

        elif args['--instrument'].lower() == 'nirspec':
            fig, ax = plt.subplots(figsize=(14,8))
            plot_single_instrument(ax, 'NIRSpec', times, minNIRSpec_PA_data, maxNIRSpec_PA_data)
            ax.set_xlim(Time(search_start, format='mjd').datetime, Time(search_end, format='mjd').datetime)

        elif args['--instrument'].lower() == 'niriss':
            fig, ax = plt.subplots(figsize=(14,8))
            plot_single_instrument(ax, 'NIRISS', times, minNIRISS_PA_data, maxNIRISS_PA_data)
            ax.set_xlim(Time(search_start, format='mjd').datetime, Time(search_end, format='mjd').datetime)

        elif args['--instrument'].lower() == 'fgs':
            fig, ax = plt.subplots(figsize=(14,8))
            plot_single_instrument(ax, 'FGS', times, minFGS_PA_data, maxFGS_PA_data)
            ax.set_xlim(Time(search_start, format='mjd').datetime, Time(search_end, format='mjd').datetime)
        
        if name is not None:
            targname = name
        else:
            targname = ''
        if args['fixed']:
            suptitle = '{} (RA = {}, DEC = {})'.format(targname, args['<ra>'], args['<dec>'])
        else:
            suptitle = '{}'.format(targname, ra, dec)
        fig.suptitle(suptitle, fontsize=18)               
        fig.tight_layout()
        fig.subplots_adjust(top=0.88)

        if args['--save_plot'] is None:
            plt.show()
        else:
            plt.savefig(args['--save_plot'])


def plot_single_instrument(ax, instrument_name, t, min_pa, max_pa):

    min_pa = np.array(min_pa)
    max_pa = np.array(max_pa)
    t = np.array(t)

    if np.any(min_pa > max_pa):
        minpa_lt_maxpa = min_pa < max_pa
        minpa_gt_maxpa = min_pa > max_pa
        
        max_pa_upper = np.copy(max_pa)
        min_pa_upper = np.copy(min_pa)
        max_pa_upper[minpa_gt_maxpa] = 360
        max_pa_upper[minpa_lt_maxpa] = np.nan
        min_pa_upper[minpa_lt_maxpa] = np.nan

        max_pa_lower = np.copy(max_pa)
        min_pa_lower = np.copy(min_pa)
        min_pa_lower[minpa_gt_maxpa] = 0
        max_pa_lower[minpa_lt_maxpa] = np.nan
        min_pa_lower[minpa_lt_maxpa] = np.nan


        max_pa[minpa_gt_maxpa] = np.nan
        min_pa[minpa_gt_maxpa] = np.nan

        ax.fill_between(t, min_pa_upper, max_pa_upper, facecolor='.7', edgecolor='.7', lw=2)
        ax.fill_between(t, min_pa_lower, max_pa_lower, facecolor='.7', edgecolor='.7', lw=2)
        ax.fill_between(t, min_pa, max_pa, edgecolor='.7', facecolor='.7', lw=2)
        ax.set_ylabel("Available Position Angle (Degree)")
        ax.set_title(instrument_name)
        ax.fmt_xdata = DateFormatter('%Y-%m-%d')    


    else:
        ax.fill_between(t, min_pa, max_pa, edgecolor='none', facecolor='.7')
        ax.set_ylabel("Available Position Angle (Degree)")
        ax.set_title(instrument_name)
        ax.fmt_xdata = DateFormatter('%Y-%m-%d')    
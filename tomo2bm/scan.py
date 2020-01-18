'''
    Tomo Scan Lib for Sector 2-BM  using Point Grey Grasshooper3 or FLIR Oryx cameras
    
'''
from __future__ import print_function

import sys
import json
import time
from epics import PV
import h5py
import shutil
import os
import imp
import traceback
import math
import signal
import logging
import numpy as np

from tomo2bm import aps2bm
from tomo2bm import dm
from tomo2bm import log
from tomo2bm import flir

global_PVs = {}

def fly_sleep(params):

    tic =  time.time()
    # aps2bm.update_variable_dict(params)
    global_PVsx = aps2bm.init_general_PVs(global_PVs, params)
    try: 
        detector_sn = global_PVs['Cam1_SerialNumber'].get()
        if ((detector_sn == None) or (detector_sn == 'Unknown')):
            log.info('*** The Point Grey Camera with EPICS IOC prefix %s is down' % params.camera_ioc_prefix)
            log.info('  *** Failed!')
        else:
            log.info('*** The Point Grey Camera with EPICS IOC prefix %s and serial number %s is on' \
                        % (params.camera_ioc_prefix, detector_sn))
            
            # calling global_PVs['Cam1_AcquireTime'] to replace the default 'ExposureTime' with the one set in the camera
            params.exposure_time = global_PVs['Cam1_AcquireTime'].get()
            # calling calc_blur_pixel() to replace the default 'SlewSpeed' 
            blur_pixel, rot_speed, scan_time = calc_blur_pixel(global_PVs, params)
            params.slew_speed = rot_speed

            # init camera
            flir.pgInit(global_PVs, params)

            # set sample file name
            fname = str('{:03}'.format(global_PVs['HDF1_FileNumber'].get())) + '_' + global_PVs['Sample_Name'].get(as_string=True)

            tomo_fly_scan(global_PVs, params, fname)

            log.info(' ')
            log.info('  *** Total scan time: %s minutes' % str((time.time() - tic)/60.))
            log.info('  *** Data file: %s' % global_PVs['HDF1_FullFileName_RBV'].get(as_string=True))

            log.info('  *** Moving rotary stage to start position')
            global_PVs["Motor_SampleRot"].put(0, wait=True, timeout=600.0)
            log.info('  *** Moving rotary stage to start position: Done!')

            global_PVs['Cam1_ImageMode'].put('Continuous')

            dm.scp(global_PVs, params)

            log.info('  *** Done!')

    except  KeyError:
        log.error('  *** Some PV assignment failed!')
        pass


def dummy_tomo_fly_scan(global_PVs, params, fname):
    log.info(' ')
    log.info('  *** start_scan')

    def cleanup(signal, frame):
        stop_scan(global_PVs, params)
        sys.exit(0)
    signal.signal(signal.SIGINT, cleanup)


def params.recursive_filter_n_images:

    if (params.recursive_filter == False):
        params.recursive_filter_n_images = 1 
    return params.recursive_filter_n_images

   
def tomo_fly_scan(global_PVs, params, fname):
    log.info(' ')
    log.info('  *** start_scan')

    def cleanup(signal, frame):
        stop_scan(global_PVs, params)
        sys.exit(0)
    signal.signal(signal.SIGINT, cleanup)

    # if params.has_key('StopTheScan'):
    #     stop_scan(global_PVs, params)
    #     return

    # moved to outer loop in main()
    # pgInit(global_PVs, params)
    params.recursive_filter_n_images
    
    setPSO(global_PVs, params)

    # fname = global_PVs['HDF1_FileName'].get(as_string=True)
    log.info('  *** File name prefix: %s' % fname)

    flir.pgSet(global_PVs, params, fname) 

    aps2bm.open_shutters(global_PVs, params)

    move_sample_in(global_PVs, params)

    # # run fly scan
    theta = flir.pgAcquisition(global_PVs, params)

    theta_end =  global_PVs['Motor_SampleRot_RBV'].get()
    if (0 < theta_end < 180.0):
        # print('\x1b[2;30;41m' + '  *** Rotary Stage ERROR. Theta stopped at: ***' + theta_end + '\x1b[0m')
        log.error('  *** Rotary Stage ERROR. Theta stopped at: %s ***' % str(theta_end))

    move_sample_out(global_PVs, params)
    flir.pgAcquireFlat(global_PVs, params)
    move_sample_in(global_PVs, params)

    aps2bm.close_shutters(global_PVs, params)
    time.sleep(2)

    flir.pgAcquireDark(global_PVs, params)

    flir.checkclose_hdf(global_PVs, params)

    flir.add_theta(global_PVs, params, theta)


########################################################################
def calc_blur_pixel(global_PVs, params):
    """
    Calculate the blur error (pixel units) due to a rotary stage fly scan motion durng the exposure.
    
    Parameters
    ----------
    params.exposure_time: float
        Detector exposure time
    params.ccd_readout : float
        Detector read out time
    variableDict[''roiSizeX''] : int
        Detector X size
    params.sample_rotation_end : float
        Tomographic scan angle end
    params.sample_rotation_start : float
        Tomographic scan angle start
    variableDict[''Projections'] : int
        Numember of projections

    Returns
    -------
    float
        Blur error in pixel. For good quality reconstruction this should be < 0.2 pixel.
    """

    angular_range =  params.sample_rotation_end -  params.sample_rotation_start
    angular_step = angular_range/params.num_projections
    scan_time = params.num_projections * (params.exposure_time + params.ccd_readout)
    rot_speed = angular_range / scan_time
    frame_rate = params.num_projections / scan_time
    blur_delta = params.exposure_time * rot_speed
 
   
    mid_detector = global_PVs['Cam1_MaxSizeX_RBV'].get() / 2.0
    blur_pixel = mid_detector * (1 - np.cos(blur_delta * np.pi /180.))

    log.info(' ')
    log.info('  *** Calc blur pixel')
    log.info("  *** *** Total # of proj: %s " % params.num_projections)
    log.info("  *** *** Exposure Time: %s s" % params.exposure_time)
    log.info("  *** *** Readout Time: %s s" % params.ccd_readout)
    log.info("  *** *** Angular Range: %s degrees" % angular_range)
    log.info("  *** *** Camera X size: %s " % global_PVs['Cam1_SizeX'].get())
    log.info(' ')
    log.info("  *** *** *** *** Angular Step: %f degrees" % angular_step)   
    log.info("  *** *** *** *** Scan Time: %f s" % scan_time) 
    log.info("  *** *** *** *** Rot Speed: %f degrees/s" % rot_speed)
    log.info("  *** *** *** *** Frame Rate: %f fps" % frame_rate)
    log.info("  *** *** *** *** Max Blur: %f pixels" % blur_pixel)
    log.info('  *** Calc blur pixel: Done!')
    
    return blur_pixel, rot_speed, scan_time


def move_sample_out(global_PVs, params):
    log.info('      *** Sample out')
    if not (params.sample_move_freeze):
        if (params.sample_in_out_vertical):
            log.info('      *** *** Move Sample Y out at: %f' % params.sample_out_position)
            global_PVs['Motor_SampleY'].put(str(params.sample_out_position), wait=True, timeout=1000.0)                
            if wait_pv(global_PVs['Motor_SampleY'], float(params.sample_out_position), 60) == False:
                log.error('Motor_SampleY did not move in properly')
                log.error(global_PVs['Motor_SampleY'].get())
        else:
            if (params.use_furnace):
                log.info('      *** *** Move Furnace Y out at: %f' % params.furnace_out_position)
                global_PVs['Motor_FurnaceY'].put(str(params.furnace_out_position), wait=True, timeout=1000.0)
                if wait_pv(global_PVs['Motor_FurnaceY'], float(params.furnace_out_position), 60) == False:
                    log.error('Motor_FurnaceY did not move in properly')
                    log.error(global_PVs['Motor_FurnaceY'].get())
            log.info('      *** *** Move Sample X out at: %f' % params.sample_out_position)
            global_PVs['Motor_SampleX'].put(str(params.sample_out_position), wait=True, timeout=1000.0)
            if wait_pv(global_PVs['Motor_SampleX'], float(params.sample_out_position), 60) == False:
                log.error('Motor_SampleX did not move in properly')
                log.error(global_PVs['Motor_SampleX'].get())
    else:
        log.info('      *** *** Sample Stack is Frozen')


def move_sample_in(global_PVs, params):
    log.info('      *** Sample in')
    if not (params.sample_move_freeze):
        if (params.sample_in_out_vertical):
            log.info('      *** *** Move Sample Y in at: %f' % params.sample_in_position)
            global_PVs['Motor_SampleY'].put(str(params.sample_in_position), wait=True, timeout=1000.0)                
            if wait_pv(global_PVs['Motor_SampleY'], float(params.sample_in_position), 60) == False:
                log.error('Motor_SampleY did not move in properly')
                log.error(global_PVs['Motor_SampleY'].get())
        else:
            log.info('      *** *** Move Sample X in at: %f' % params.sample_in_position)
            global_PVs['Motor_SampleX'].put(str(params.sample_in_position), wait=True, timeout=1000.0)
            if wait_pv(global_PVs['Motor_SampleX'], float(params.sample_in_position), 60) == False:
                log.error('Motor_SampleX did not move in properly')
                log.error(global_PVs['Motor_SampleX'].get())
            if (params.use_furnace):
                log.info('      *** *** Move Furnace Y in at: %f' % params.furnace_in_position)
                global_PVs['Motor_FurnaceY'].put(str(params.furnace_in_position), wait=True, timeout=1000.0)
                if wait_pv(global_PVs['Motor_FurnaceY'], float(params.furnace_in_position), 60) == False:
                    log.error('Motor_FurnaceY did not move in properly')
                    log.error(global_PVs['Motor_FurnaceY'].get())
    else:
        log.info('      *** *** Sample Stack is Frozen')

def stop_scan(global_PVs, params):
        log.info(' ')
        log.error('  *** Stopping the scan: PLEASE WAIT')
        global_PVs['Motor_SampleRot_Stop'].put(1)
        global_PVs['HDF1_Capture'].put(0)
        wait_pv(global_PVs['HDF1_Capture'], 0)
        pgInit(global_PVs, params)
        log.error('  *** Stopping scan: Done!')
        ##pgInit(global_PVs, params)


def setPSO(global_PVs, params):

    acclTime = 1.0 * params.slew_speed/params.accl_rot
    scanDelta = abs(((float(params.sample_rotation_end) - float(params.sample_rotation_start))) / ((float(params.num_projections)) * float(params.recursive_filter_n_images)))

    log.info('  *** *** start_pos %f' % float(params.sample_rotation_start))
    log.info('  *** *** end pos %f' % float(params.sample_rotation_end))

    global_PVs['Fly_StartPos'].put(float(params.sample_rotation_start), wait=True)
    global_PVs['Fly_EndPos'].put(float(params.sample_rotation_end), wait=True)
    global_PVs['Fly_SlewSpeed'].put(params.slew_speed, wait=True)
    global_PVs['Fly_ScanDelta'].put(scanDelta, wait=True)
    time.sleep(3.0)

    calc_num_proj = global_PVs['Fly_Calc_Projections'].get()
    
    if calc_num_proj == None:
        log.error('  *** *** Error getting fly calculated number of projections!')
        calc_num_proj = global_PVs['Fly_Calc_Projections'].get()
        log.error('  *** *** Using %s instead of %s' % (calc_num_proj, params.num_projections))
    if calc_num_proj != int(params.num_projections):
        log.warning('  *** *** Changing number of projections from: %s to: %s' % (params.num_projections, int(calc_num_proj)))
        params.num_projections = int(calc_num_proj)
    log.info('  *** *** Number of projections: %d' % int(params.num_projections))
    log.info('  *** *** Fly calc triggers: %d' % int(calc_num_proj))
    global_PVs['Fly_ScanControl'].put('Standard')

    log.info(' ')
    log.info('  *** Taxi before starting capture')
    global_PVs['Fly_Taxi'].put(1, wait=True)
    wait_pv(global_PVs['Fly_Taxi'], 0)
    log.info('  *** Taxi before starting capture: Done!')

########################################################################


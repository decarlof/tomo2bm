#!/usr/bin/env python
# -*- coding: utf-8 -*-
'''
    FlyScan for Sector 2-BM

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
from datetime import datetime
import numpy as np
import pathlib

import libs.aps2bm_lib as aps2bm_lib
import libs.scan_lib as scan_lib
import libs.log_lib as log_lib
import libs.dm_lib as dm_lib

global variableDict

variableDict = {
        'StartX': -7.6,                  # set X starting point of the mosaic scan 
        'EndX': 7.6,                     # set X ending point of the mosaic scan; this point will be included in the scan
        'StepSizeX': 3.8,                # set X step of the mosaic scan 
        'StartY': 11,                 # same as the X above. For one scan mosaic in X only
        'EndY': 13,                   # set StartY to the desided Y position, EndY to the same value and
        'StepSizeY': 1,                  # an StepSizeY larger than (EndY - StartY)
        # 'SampleXIn': 0.0,              # not used in x-y scan
        'SampleXOut': -14.0,
        # 'SampleYIn': 0,                 # to use Y change the sampleInOutVertical = True
        # 'SampleYOut': -4,
        'SampleInOutVertical': False,     # False: use X to take the white field
        'SampleMoveEnabled': True,        # False to freeze sample motion during white field data collection
        'SampleRotStart': 0.0,
        'SampleRotEnd':180.0,
        'Projections': 1500,
        'NumWhiteImages': 20,
        'NumDarkImages': 20,
        # ####################### DO NOT MODIFY THE PARAMETERS BELOW ###################################
        # 'CCD_Readout': 0.006,             # options: 1. 8bit: 0.006, 2. 16-bit: 0.01
        'CCD_Readout': 0.01,             # options: 1. 8bit: 0.006, 2. 16-bit: 0.01
        'Station': '2-BM-A',
        'ExposureTime': 0.01,             # to use this as default value comment the variableDict['ExposureTime'] = global_PVs['Cam1_AcquireTime'].get() line
        # 'roiSizeX': 2448, 
        # 'roiSizeY': 2048,       
        'SlewSpeed': 5.0,                 # to use this as default value comment the calc_blur_pixel(global_PVs, variableDict) function below
        'AcclRot': 1.0,
        'IOC_Prefix': '2bmbSP1:',         # options: 1. PointGrey: '2bmbPG3:', 2. Gbe '2bmbSP1:' 
        'FileWriteMode': 'Stream',
        'ShutterOpenDelay': 0.00,
        'Recursive_Filter_Enabled': False,
        'Recursive_Filter_N_Images': 4,
        'UseFurnace': False,              # True: moves the furnace  to FurnaceYOut position to take white field: 
                                          #       Note: this flag is active ONLY when both 1. and 2. are met:
                                          #           1. SampleMoveEnabled = True
                                          #           2. SampleInOutVertical = False  
        'FurnaceYIn': 0.0,                
        'FurnaceYOut': 48.0,
        'RemoteAnalysisDir' : 'tomo@handyn:/local/data/'
        }

global_PVs = {}


def getVariableDict():
    global variableDict
    return variableDict


def main():
    # create logger
    # # python 3.5+ 
    # home = str(pathlib.Path.home())
    home = os.path.expanduser("~")
    logs_home = home + '/logs/'

    # make sure logs directory exists
    if not os.path.exists(logs_home):
        os.makedirs(logs_home)

    lfname = logs_home + datetime.strftime(datetime.now(), "%Y-%m-%d_%H:%M:%S") + '.log'
    log_lib.setup_logger(lfname)


    tic =  time.time()
    aps2bm_lib.update_variable_dict(variableDict)
    aps2bm_lib.init_general_PVs(global_PVs, variableDict)
    
    try: 
        detector_sn = global_PVs['Cam1_SerialNumber'].get()
        if ((detector_sn == None) or (detector_sn == 'Unknown')):
            log_lib.info('*** The Point Grey Camera with EPICS IOC prefix %s is down' % variableDict['IOC_Prefix'])
            log_lib.info('  *** Failed!')
        else:
            log_lib.info('*** The Point Grey Camera with EPICS IOC prefix %s and serial number %s is on' \
                        % (variableDict['IOC_Prefix'], detector_sn))
            
            # calling global_PVs['Cam1_AcquireTime'] to replace the default 'ExposureTime' with the one set in the camera
            variableDict['ExposureTime'] = global_PVs['Cam1_AcquireTime'].get()
            # calling calc_blur_pixel() to replace the default 'SlewSpeed' 
            blur_pixel, rot_speed, scan_time = aps2bm_lib.calc_blur_pixel(global_PVs, variableDict)
            variableDict['SlewSpeed'] = rot_speed

            # get sample file name
            # fname = global_PVs['HDF1_FileName'].get(as_string=True)

            start_y = variableDict['StartY']
            end_y = variableDict['EndY']
            step_size_y = variableDict['StepSizeY']


            start_x = variableDict['StartX']
            end_x = variableDict['EndX']
            step_size_x = variableDict['StepSizeX']

            # moved pgInit() here from tomo_fly_scan() 
            aps2bm_lib.pgInit(global_PVs, variableDict)

            log_lib.info(' ')
            log_lib.info("  *** Running %d scans" % (len(np.arange(start_x, end_x, step_size_x)) * len(np.arange(start_y, end_y, step_size_y))))
            log_lib.info(' ')
            log_lib.info('  *** Horizontal Positions (mm): %s' % np.arange(start_x, end_x, step_size_x))
            log_lib.info('  *** Vertical Positions (mm): %s' % np.arange(start_y, end_y, step_size_y))
            
            h = 0
            v = 0
            
            stop_x = end_x + step_size_x
            stop_y = end_y + step_size_y
            
            for i in np.arange(start_y, stop_y, step_size_y):
                # log_lib.info('  *** Moving rotary stage to start position')
                # global_PVs["Motor_SampleRot"].put(0, wait=True, timeout=600.0)
                # log_lib.info('  *** Moving rotary stage to start Y position: Done!')
                log_lib.info(' ')
                log_lib.info('  *** The sample vertical position is at %s mm' % (i))
                global_PVs['Motor_SampleY'].put(i, wait=True)
                for j in np.arange(start_x, stop_x, step_size_x):
                    log_lib.info('  *** The sample horizontal position is at %s mm' % (j))
                    # global_PVs['Motor_SampleX'].put(j, wait=True)
                    variableDict['SampleXIn'] = j
                    fname = str('{:03}'.format(global_PVs['HDF1_FileNumber'].get())) + '_' + "".join([chr(c) for c in global_PVs['Sample_Name'].get()]) + '_y' + v + 'x' + h
                    scan_lib.tomo_fly_scan(global_PVs, variableDict, fname)
                    h = h + 1
                log_lib.info(' ')
                log_lib.info('  *** Total scan time: %s minutes' % str((time.time() - tic)/60.))
                log_lib.info('  *** Data file: %s' % global_PVs['HDF1_FullFileName_RBV'].get(as_string=True))
                v = v + 1
                h = 0
                dm_lib.scp(global_PVs, variableDict)

            log_lib.info('  *** Moving rotary stage to start position')
            global_PVs["Motor_SampleRot"].put(0, wait=True, timeout=600.0)
            log_lib.info('  *** Moving rotary stage to start position: Done!')

            global_PVs['Cam1_ImageMode'].put('Continuous')

            
            log_lib.info('  *** Done!')

    except  KeyError:
        log_lib.error('  *** Some PV assignment failed!')
        pass
        
        

if __name__ == '__main__':
    main()

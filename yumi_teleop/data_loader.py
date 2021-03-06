'''
Utility functions to load yumi teleop recorded data into numpy arrays
Author: Jacky Liang
'''

import os
from joblib import load
import numpy as np
from core import CSVModel, RigidTransform
import IPython

ROOT_PATH = '/mnt/hdd/data/'

def load_records(mode):
    if mode not in ('k', 't'):
        raise ValueError("Can only accept k (Kinesthetic) or t (Teleop) as modes. Got {}".format(mode))

    path = os.path.join(ROOT_PATH, 'yumi_{}'.format('kinesthetics' if mode == 'k' else 'teleop'), 'demo_records.csv')
    records = CSVModel.load(path)
    return records

def load_registration_tf(trial_path, device):
    if device not in ('webcam', 'primesense'):
        raise ValueError("Can only accept webcam or primesense. Got {}".format(device))
    return RigidTransform.load(os.path.join(trial_path, '{}_overhead_to_world.tf'.format(device)))

def prune_data(lst, trial):
    try:
        prune = eval(trial['comments']) #TODO THIS IS VERY HACKY
    except Exception:
        return lst

    try:
        lo, hi = prune[1]
    except Exception:
        return lst

    return lst[lo:hi+1]

def load_poses(trial, arm_name, prune=True, subsample=1, euler=True):
    '''
    Returns n by 6 numpy array. n is # of time steps.
    the first 3 cols are x-y-z translation, last 3 are sxyz euler angles
    '''
    if arm_name not in ('left', 'right'):
        raise ValueError("Arm name can only be left or right. Got {}".format(arm_name))
    trial_path = trial['trial_path']
    poses_raw = load(os.path.join(trial_path, 'poses_{}.jb'.format(arm_name)))
    if prune:
        poses_raw = prune_data(poses_raw, trial)
    poses = [x[1][1] for x in poses_raw]
    if subsample > 1:
        poses = poses[::subsample]
    if not euler:
        return poses
    poses_lst = [np.r_[p.translation, p.quaternion] for p in poses]
    return np.array(poses_lst)

def load_joints(trial, arm_name):
    '''
    Returns n by 7 numpy array. n is # of time steps. the ith col is the angle of the ith joint
    '''
    if arm_name not in ('left', 'right'):
        raise ValueError("Arm name can only be left or right. Got {}".format(arm_name))
    trial_path = trial['trial_path']
    states_raw = load(os.path.join(trial_path, 'states_{}.jb'.format(arm_name)))
    states_raw = prune_data(states_raw, trial)
    states = [x[1][1] for x in states_raw]
    joints_lst = [s.joints for s in states]
    return np.array(joints_lst)

def jb_number(name):
    try:
        return int(name[:name.index('.jb')])
    except Exception:
        return float('inf')

def concat_chunks(path):
    all_chunks = os.listdir(path)
    all_chunks.sort(key=jb_number)
    data = []
    for chunk in all_chunks:
        if chunk != '.finished':
            data.extend(load(os.path.join(path, chunk)))

    return data

def load_images(trial, device, prune=True, subsample=1, numpy=True):
    '''
    load n by h by w by (3, 1) (3 if webcam, 1 if depth) array
    '''
    if device not in ('webcam', 'kinect_depth', 'primesense_depth', 'kinect_color'):
        raise ValueError("Can only accept devices: webcam, kinect_depth, kinect_color, or primesense_depth. Got {}".format(device))
    if isinstance(trial, str):
        trial_path = trial
    else:
        trial_path = trial['trial_path']
    data_path = os.path.join(trial_path, device)
    data = concat_chunks(data_path)

    if not isinstance(trial, str):
        if prune:
            data = prune_data(data, trial)

    if subsample > 1:
        data = data[::subsample]

    frames = [x[1].data for x in data]
    if numpy:
        return np.array(frames)
    else:
        return frames

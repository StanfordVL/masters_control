#!/usr/bin/env python
"""
MastersYuMiConnector that subscribers to poses of masters and publishes corresponding
target poses for the YuMi.
Meant to operate along yumi_teleop_client and yumi_teleop_host
Author: Jacky Liang
"""
import rospy, os
from std_msgs.msg import Bool
from geometry_msgs.msg import Pose
from time import time
from masters_control.srv import pose_str
import numpy as np
from core import RigidTransform
from yumi_teleop import T_to_ros_pose, ros_pose_to_T
from multiprocessing import Queue

_T_MC_YCR = RigidTransform(rotation=[[0,-1,0],
                                        [1,0,0],
                                        [0,0,1]],
                                from_frame='yumi_current_ref', to_frame='masters_current')

_T_YIR_MI = RigidTransform(rotation=[[0,1,0],
                                      [-1,0,0],
                                      [0,0,1]],
                            from_frame='masters_init', to_frame='yumi_init_ref')

START_TIME = time()

class MastersYuMiConnector:

    def __init__(self, name):
        self.clutch_state = False
        self._clutch_i = 0

        # masters reference poses
        self.T_mz_cu_t = None
        self.T_w_cu_t = None
        self.T_mzr_mz = None
        self.T_mc_mcr = None
        self.T_w_mc = None
        self.T_w_cd_t1 = None

        # yumi reference poses
        self.T_w_yi = None
        self.T_yi_yir = None
        self.T_ycr_yc = None

        full_ros_namespace = "/dvrk/" + name
        rospy.init_node('master_yumi_connector',anonymous=True)
        rospy.loginfo("Initializing node")

        self.cb_prop_q = Queue()

        # publishing to /yumi/r or /yumi/l
        self.pub_name = '/yumi/{0}'.format(name[-1].lower())
        self.pub = rospy.Publisher(self.pub_name, Pose, queue_size=1)

        self.has_zeroed = False
        self.has_clutched_down = False
        self.has_clutched_up = False

        # subscribing to clutch and rel pose
        rospy.loginfo("Subscribing to position_cartesian_current for {0}".format(name))
        self.rel_pose_sub = rospy.Subscriber('{0}/position_cartesian_current'.format(full_ros_namespace),
                         Pose, self._position_cartesian_current_callback)

        rospy.loginfo("Subscribing to clutch")
        self.clutch_sub = rospy.Subscriber('/dvrk/footpedals/clutch', Bool, self._clutch_callback)

        rospy.loginfo("Waiting for first resest init pose...")
        self.times = []

    def _update_cb_objs(self):
        if self.cb_prop_q.qsize() > 0:
            for key, val in self.cb_prop_q.get().items():
                if key == 'has_zeroed':
                    rospy.loginfo("{} setting zero to {} at {}".format(self.pub_name, val, time() - START_TIME))
                setattr(self, key, val)

    def _reset_init_poses(self, yumi_pose):
        rospy.loginfo("Reset Init Pose for {} at {}".format(self.pub_name, time() - START_TIME))
        rospy.loginfo('Received yumi pose for {} is {}'.format(self.pub_name, yumi_pose.translation))
        self.cb_prop_q.put({
            'has_zeroed': False
        })

        self.T_mz_cu_t = RigidTransform(from_frame=self._clutch('up'), to_frame='masters_zero')
        self.T_w_cu_t = self.T_w_mc.as_frames(self._clutch('up'), 'world')
        self.T_mzr_mz = RigidTransform(rotation=self.T_w_cu_t.rotation,
                                    from_frame='masters_zero', to_frame='masters_zero_ref')
        self.T_mc_mcr = RigidTransform(rotation=self.T_w_cu_t.inverse().rotation,
                                    from_frame='masters_current_ref', to_frame='masters_current')

        self.T_w_yi = yumi_pose.copy()
        self.T_yi_yir = RigidTransform(rotation=self.T_w_yi.inverse().rotation, from_frame='yumi_init_ref', to_frame='yumi_init')
        self.T_ycr_yc = RigidTransform(rotation=self.T_w_yi.rotation, from_frame='yumi_current', to_frame='yumi_current_ref')

        self.cb_prop_q.put({
            'T_w_cu_t': self.T_w_cu_t,
            'T_mzr_mz': self.T_mzr_mz,
            'T_mc_mcr': self.T_mc_mcr,
            'T_w_yi': self.T_w_yi,
            'T_yi_yir': self.T_yi_yir,
            'T_ycr_yc': self.T_ycr_yc
        })

        self.cb_prop_q.put({
            'has_zeroed': True
        })

        rospy.loginfo("Done Init Pose for {} at {}".format(self.pub_name, time() - START_TIME))

    def _clutch(self, state):
        return 'clutch_{0}_{1}'.format(state, self._clutch_i)

    def _position_cartesian_current_callback(self, ros_pose):
        # start = time()
        self.T_w_mc = ros_pose_to_T(ros_pose, 'masters_current', 'world')
        self._update_cb_objs()
        if not self.has_zeroed:
            return

        # only update YuMi if clutch is not pressed
        if not self.clutch_state:
            T_mz_mc = self.T_mz_cu_t * self.T_w_cu_t.inverse() * self.T_w_mc
            T_mzr_mcr = self.T_mzr_mz * T_mz_mc * self.T_mc_mcr

            T_mi_mc = T_mzr_mcr.as_frames("masters_current", "masters_init")
            T_yir_ycr = _T_YIR_MI * T_mi_mc * _T_MC_YCR
            T_w_yc = self.T_w_yi * self.T_yi_yir * T_yir_ycr * self.T_ycr_yc

            self.pub.publish(T_to_ros_pose(T_w_yc))
            # self.times.append(time() - start)
            # rospy.loginfo("Average forwarding time is {}".format(np.mean(self.times)))

    def _clutch_callback(self, msg):
        if not self.has_zeroed:
            return

        clutch_down = msg.data

        if clutch_down:
            self._clutch_i += 1
            rospy.loginfo("Got clutch down: {0}".format(self._clutch_i))
            # clutch down
            self.T_w_cd_t1 = self.T_w_mc.as_frames(self._clutch('down'), 'world')
        else:
            # clutch up
            rospy.loginfo("Updating clutch up for {0}".format(self._clutch_i))
            self.T_mz_cu_t = self.T_mz_cu_t * self.T_w_cu_t.inverse() * \
                               self.T_w_cd_t1 * RigidTransform(from_frame=self._clutch('up'), to_frame=self._clutch('down'))

            # updating last known clutch up pose
            self.T_w_cu_t = self.T_w_mc.as_frames(self._clutch('up'), 'world')

        self.clutch_state = clutch_down

    def shutdown(self):
        self.rel_pose_sub.unregister()
        self.clutch_sub.unregister()

if __name__ == "__main__":
    left = MastersYuMiConnector("MTML")
    right = MastersYuMiConnector("MTMR")

    def reset_init_poses(res):
        left._reset_init_poses(ros_pose_to_T(res.left, 'yumi_init', 'world'))
        right._reset_init_poses(ros_pose_to_T(res.right, 'yumi_init', 'world'))
        return 'ok'

    init_pose_reset_service = rospy.Service('masters_yumi_transform_reset_init_poses', pose_str, reset_init_poses)

    def shutdown_hook():
        left.shutdown()
        right.shutdown()
    rospy.on_shutdown(shutdown_hook)

    rospy.spin()

import rospy
import random
from scout.msg import RL_input_msgs
from geometry_msgs.msg import Twist
from visualization_msgs.msg import Marker

import tensorflow as tf
import numpy as np
import matplotlib.pyplot as plt
import time
import math
import os
import csv

import subprocess
import ppo_algo_multi_goal as ppo_algo
import ppo_env_multi_goal as ppo_env


EP_MAX = 1000000
EP_LEN = 600
BATCH = 32
GAMMA = 0.9

METHOD = [
    dict(name='kl_pen', kl_target=0.01, lam=0.5),   # KL penalty
    dict(name='clip', epsilon=0.2),                 # Clipped surrogate objective, find this is better
][1]

# save rewards data as npy file of every train
def save_plot(ep, ep_r, TRAIN_TIME, PLOT_EPISODE, PLOT_REWARD):
    plot_path = '/home/xyw/BUAA/Graduation/src/scout/result/multi/img/PPO_%i.npy' %(TRAIN_TIME)
    PLOT_EPISODE = np.append(PLOT_EPISODE, ep)
    PLOT_REWARD = np.append(PLOT_REWARD, ep_r)
    PLOT_RESULT = np.concatenate([[PLOT_EPISODE], [PLOT_REWARD]])
    np.save(plot_path, PLOT_RESULT)
    return PLOT_EPISODE, PLOT_REWARD

def save_behavior(ep, TRAIN_TIME, PLOT_EPISODE, sucess_time, collide_time, overarea_time, sucess_list, collide_list, overarea_list):
    plot_path = '/home/xyw/BUAA/Graduation/src/scout/result/multi/img/PPO_Behavior_%i.npy' %(TRAIN_TIME)
    
    sucess_list = np.append(sucess_list, sucess_time)
    collide_list = np.append(collide_list, collide_time)
    overarea_list = np.append(overarea_list, collide_time)

    Behavior_result = np.concatenate([[PLOT_EPISODE], [sucess_list], [collide_list], [overarea_list]])
    np.save(plot_path, Behavior_result)

    return sucess_list, collide_list, overarea_list

# save the parameters as csv file of every train
def save_para(ppo, env, TRAIN_TIME):
    csvfile = open('/home/xyw/BUAA/Graduation/src/scout/result/multi/img/PPO_para.csv', 'a+', newline='')
    writer = csv.writer(csvfile)
    data = ['%i' %(TRAIN_TIME), '%i' %(BATCH), '%.1e' %(ppo.A_LR), '%.1e' %(ppo.C_LR)]
    writer.writerow(data)
    csvfile.close()

def update(ppo, s_, buffer_r, buffer_s, buffer_a):

    v_s_ = ppo.get_v(s_)
    discounted_r = []
    for r in buffer_r[::-1]:
        v_s_ = r + GAMMA * v_s_
        discounted_r.append(v_s_)
    discounted_r.reverse()

    bs, ba, br = np.vstack(buffer_s), np.vstack(buffer_a), np.array(discounted_r)[:, np.newaxis]
    buffer_s = []
    buffer_a = []
    buffer_r = []
    
    ppo.update(bs, ba, br)
    
if __name__ == '__main__':
    rospy.init_node('RL', anonymous=True)

    for TRAIN_TIME in range(50):

        PLOT_EPISODE = np.array([],dtype = int)
        PLOT_REWARD = np.array([], dtype = float)

        sucess_list = np.array([],dtype = int)
        collide_list = np.array([], dtype = int)
        overarea_list = np.array([], dtype = int)

        # if BREAK = 0, means action is not 'nan'.
        # if BREAK = 1, means action is 'nan', reset ppo and env to another train.
        BREAK = 0

        # 1. fix LR: Change LR in ppo_algo.py, and uncomment restore function.
        # 2. random LR: Change LR in ppo_algo.py, and conmment restore function.
        ppo = ppo_algo.ppo(TRAIN_TIME)
        print('\n Training Start')

        # 0: basic model
        ppo.restore(0)

        env = ppo_env.env()
        env.rand_goal()
        print('Goal is %i, %i' %(env.goal_x, env.goal_y))

        save_para(ppo, env, TRAIN_TIME+1)

        all_ep_r = []

        for ep in range(EP_MAX):
            a_init = [0, 0]
            s = env.set_init_pose()

            buffer_s = []
            buffer_a = []
            buffer_r = []

            ep_r = 0
            time.sleep(0.1)

            sucess_time = 0
            overarea_time = 0
            collide_time = 0

            for t in range(EP_LEN):

                a =  ppo.choose_action(s)
                if np.isnan(a[0]) or np.isnan(a[1]):
                    BREAK = 1

                    # record the information of nan situation in order to find out which part has problem
                    ppo.write_log(TRAIN_TIME, ep, t, a, s_, r)

                    print('Warning: Action is nan. Restart Train')
                    break
                    # os._exit(0)

                env.set_action(a)

                s_= env.compute_state()

                collide = env.get_collision_info()
                overspeed, current_dis_from_des_point = env.compute_param()

                # collide, overspeed, current_dis_from_des_point and t to judge whether it is end of episode
                r = env.compute_reward(s_, collide, overspeed, current_dis_from_des_point)

                ppo.write_log(TRAIN_TIME, ep, t, a, s_, r)

                if ep == 0:
                    s_buff = s[np.newaxis, ...]

                s_buff = s_[np.newaxis, ...]

                buffer_s.append(s_buff)
                buffer_a.append(a)
                buffer_r.append((r+8)/8)    # normalize reward, find to be useful
                s = s_
                ep_r += r
                
                # Batch end normally
                if (t+1) % BATCH == 0 or t == EP_LEN-1:
                    update(ppo, s_, buffer_r, buffer_s, buffer_a)

                # Batch end with special behaviors
                if current_dis_from_des_point < env.reach_goal_circle:
                    update(ppo, s_, buffer_r, buffer_s, buffer_a)
                    sucess_time += 1
                    env.rand_goal()
                    print('Sucess, Next Goal is %i, %i' %(env.goal_x, env.goal_y))
            
                # if collide == 1:
                #     update(ppo, s_, buffer_r, buffer_s, buffer_a)
                #     collide_time += 1
                #     print('Collision')
                #     break

                # elif current_dis_from_des_point > env.limit_circle:
                #     update(ppo, s_, buffer_r, buffer_s, buffer_a)
                #     overarea_time += 1
                #     print('Over-area')
                #     break         
            
            # Set the beginning action of robot in next episode, or it would be set by last time
            env.set_action(a_init)

            # Print the result of episode reward
            if ep == 0: all_ep_r.append(ep_r)
            else: all_ep_r.append(all_ep_r[-1]*0.9 + ep_r*0.1)
            print(
                'Ep: %i' % ep,
                "|Ep_r: %.3f" % ep_r,
                ("|Lam: %.4f" % METHOD['lam']) if METHOD['name'] == 'kl_pen' else '',
            )

            # Save reward data for plot
            PLOT_EPISODE, PLOT_REWARD = save_plot(ep, ep_r, TRAIN_TIME, PLOT_EPISODE, PLOT_REWARD)

            # Save behavior data for plot
            # sucess_list, collide_list, overarea_list = save_behavior(ep, TRAIN_TIME, PLOT_EPISODE,
            #                                         sucess_time, collide_time, overarea_time, 
            #                                         sucess_list, collide_list, overarea_list)
            
            # Save model
            if ep % 200 == 0:
                 ppo.save(TRAIN_TIME+1)

            # Reset gazebo environment
            env.reset_env()
            
            if BREAK == 1:
                break
        
        ppo.resetgraph()
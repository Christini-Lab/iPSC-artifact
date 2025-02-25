import myokit
import random
import matplotlib.pyplot as plt
import numpy as np
from scipy.signal import find_peaks
#from vc_opt_ga import simulate_model


class VCProtocol():
    def __init__(self, segments):
        self.segments = segments #list of VCSegments

    def get_protocol_length(self):
        proto_length = 0
        for s in self.segments:
            proto_length += s.duration
        
        return proto_length

    def get_myokit_protocol(self, scale=1):
        segment_dict = {'v0': f'{-82*scale}'}
        piecewise_txt = f'piecewise((engine.time >= 0 and engine.time < {500*scale}), v0, '
        current_time = 500*scale

        #piecewise_txt = 'piecewise( '
        #current_time = 0
        #segment_dict = {}

        for i, segment in enumerate(self.segments):
            start = current_time
            end = current_time + segment.duration
            curr_step = f'v{i+1}'
            time_window = f'(engine.time >= {start} and engine.time < {end})'
            piecewise_txt += f'{time_window}, {curr_step}, '

            if segment.end_voltage is None:
                segment_dict[curr_step] = f'{segment.start_voltage}'
            else:
                slope = ((segment.end_voltage - segment.start_voltage) /
                                                                segment.duration)
                intercept = segment.start_voltage - slope * start

                segment_dict[curr_step] = f'{slope} * engine.time + {intercept}'
            
            current_time = end
        
        piecewise_txt += 'vp)'

        return piecewise_txt, segment_dict, current_time
        
    def plot_protocol(self, is_shown=False):
        fig, ax = plt.subplots(1, 1, figsize=(12, 8))
        pts_v = []
        pts_t = []
        current_t = 0
        for seg in self.segments:
            pts_v.append(seg.start_voltage)
            if seg.end_voltage is None:
                pts_v.append(seg.start_voltage)
            else:
                pts_v.append(seg.end_voltage)
            pts_t.append(current_t)
            pts_t.append(current_t + seg.duration)

            current_t += seg.duration

        plt.plot(pts_t, pts_v)

        if is_shown:
            ax.spines['right'].set_visible(False)
            ax.spines['top'].set_visible(False)
            ax.set_xlabel('Time (ms)', fontsize=16)
            ax.set_xlabel('Voltage (mV)', fontsize=16)

            plt.show()

    def plot_with_curr(self, curr, cm=60):
        mod = myokit.load_model('mmt-files/kernik_2019_NaL_art.mmt')

        p = mod.get('engine.pace')
        p.set_binding(None)

        c_m = mod.get('artifact.c_m')
        c_m.set_rhs(cm)

        v_cmd = mod.get('artifact.v_cmd')
        v_cmd.set_rhs(0)
        v_cmd.set_binding('pace') # Bind to the pacing mechanism

        # Run for 20 s before running the VC protocol
        holding_proto = myokit.Protocol()
        holding_proto.add_step(-81, 30000)
        t = holding_proto.characteristic_time()
        sim = myokit.Simulation(mod, holding_proto)
        dat = sim.run(t)
        mod.set_state(sim.state())

        # Get protocol to run
        piecewise_function, segment_dict, t_max = self.get_myokit_protocol()
        mem = mod.get('artifact')

        for v_name, st in segment_dict.items():
            v_new = mem.add_variable(v_name)
            v_new.set_rhs(st)

        vp = mem.add_variable('vp')
        vp.set_rhs(0)

        v_cmd = mod.get('artifact.v_cmd')
        v_cmd.set_binding(None)
        vp.set_binding('pace')

        v_cmd.set_rhs(piecewise_function)
        times = np.arange(0, t_max, 0.1)
        ## CHANGE THIS FROM holding_proto TO SOMETHING ELSE
        sim = myokit.Simulation(mod, holding_proto)
        dat = sim.run(t_max, log_times=times)

        fig, axs = plt.subplots(3, 1, sharex=True, figsize=(12, 8))
        axs[0].plot(times, dat['membrane.V'])
        axs[0].plot(times, dat['artifact.v_cmd'], 'k--')
        axs[1].plot(times, np.array(dat['artifact.i_out']) / cm)
        axs[2].plot(times, dat[curr])

        axs[0].set_ylabel('Voltage (mV)')
        axs[1].set_ylabel('I_out (A/F)')
        axs[2].set_ylabel(curr)
        for ax in axs:
            ax.spines['right'].set_visible(False)
            ax.spines['top'].set_visible(False)
        plt.show()


class VCSegment():
    def __init__(self, duration, start_voltage, end_voltage=None):
        self.duration = duration
        self.start_voltage = start_voltage
        self.end_voltage = end_voltage


#Utility functions
def get_mod_response(f_name='./mmt/kernik_2019_mc_fixed.mmt',
                     conductances={},
                     vc_proto=None, tols=1E-8):
    mod = myokit.load_model(f_name)

    for cond, g in conductances.items():
        group, param = cond.split('.')
        val = mod[group][param].value()
        mod[group][param].set_rhs(val*g)

    p = mod.get('engine.pace')
    p.set_binding(None)

    if vc_proto is None:
        vc_proto = return_vc_proto()

    if 'myokit' not in vc_proto.__module__:
        proto = myokit.Protocol()

        proto.add_step(-80, 10000)

        piecewise, segment_dict, t_max = vc_proto.get_myokit_protocol()

        v = mod.get('membrane.V')
        v.demote()
        v.set_rhs(0)

        new_seg_dict = {}
        for k, vol in segment_dict.items():
            new_seg_dict[k] = vol

        segment_dict = new_seg_dict

        mem = mod.get('membrane')
        vp = mem.add_variable('vp')
        vp.set_rhs(0)
        vp.set_binding('pace')

        for v_name, st in segment_dict.items():
            v_new = mem.add_variable(v_name)
            v_new.set_rhs(st)

        v.set_rhs(piecewise)

        sim = myokit.Simulation(mod, proto)

        times = np.arange(0, t_max, 0.1)

        dat = sim.run(t_max, log_times=times)

    else:
        p = mod.get('engine.pace')
        p.set_binding(None)

        v = mod.get('membrane.V')
        v.demote()
        v.set_rhs(0)
        v.set_binding('pace')

        t_max = vc_proto.characteristic_time()

        sim = myokit.Simulation(mod, vc_proto)

        times = np.arange(0, t_max, 0.1)

        sim.set_tolerance(1E-6, tols)

        dat = sim.run(t_max, log_times=times)

    return times, dat


def get_single_ap(t, v):
    t = np.array(t)
    max_t = t[-1]

    min_v, max_v = np.min(v), np.max(v)

    if (max_v - min_v) < 10:
        sample_end = np.argmin(np.abs(t - 1100))
        new_t = t[0:sample_end] -100
        new_t = [-100, 1000]
        new_v = [v[0], v[0]]
        return new_t[0:2000], new_v[0:2000]

    dvdt_peaks = find_peaks(np.diff(v), distance=300, height=.2)[0]
    if dvdt_peaks.size == 0:
        sample_end = np.argmin(np.abs(t - 1100))
        new_t = t[0:sample_end] -100
        new_t = [-100, 1000]
        new_v = [v[0], v[0]]
        return new_t, new_v

    start_idx = dvdt_peaks[int(len(dvdt_peaks) / 2)]
        
    ap_start = np.argmin(np.abs(t - t[start_idx]+100))
    ap_end = np.argmin(np.abs(t - t[start_idx]-2000))

    new_t = t[ap_start:ap_end] - t[start_idx]
    new_v = v[ap_start:ap_end]
    #[plt.axvline(t[x]) for x in dvdt_peaks]
    #import pdb
    #pdb.set_trace()

    return new_t, new_v 


def get_apd90(ap_dat):
    t = ap_dat['Time (s)'].values * 1000
    v = ap_dat['Voltage (V)'].values * 1000

    if ((v.max() - v.min()) < 20):
        return None
    if v.max() < 0:
        return None

    kernel_size = 100
    kernel = np.ones(kernel_size) / kernel_size
    v_smooth = np.convolve(v, kernel, mode='same')

    peak_idxs = find_peaks(np.diff(v_smooth), height=.1, distance=1700)[0]

    if len(peak_idxs) < 2:
        return None

    #if len(peak_idxs) > 1:
    #    peak_idxs = peak_idxs[1:-1]

    all_apd90 = []
    all_apd90_idxs = []
    for st in range(0, len(peak_idxs)-2):
        end = st + 1
        min_v = np.min(v[peak_idxs[st]:peak_idxs[end]])
        min_idx = np.argmin(v[peak_idxs[st]:peak_idxs[end]])
        search_space = [peak_idxs[st], peak_idxs[st] + min_idx]
        amplitude = np.max(v[search_space[0]:search_space[1]]) - min_v
        v_90 = min_v + amplitude * .1
        idx_apd90 = np.argmin(np.abs(v[search_space[0]:search_space[1]] - v_90))
        all_apd90.append(idx_apd90 / 10)
        all_apd90_idxs.append(search_space[0] + idx_apd90)


    #min_v = np.min(v[peak_idxs[0]:peak_idxs[1]])
    #min_idx = np.argmin(v[peak_idxs[0]:peak_idxs[1]])
    #search_space = [peak_idxs[0], peak_idxs[0] + min_idx]
    #amplitude = np.max(v[search_space[0]:search_space[1]]) - min_v
    #v_90 = min_v + amplitude * .1
    #idx_apd90 = np.argmin(np.abs(v[search_space[0]:search_space[1]] - v_90))


    #if np.mean(all_apd90) > 300:
    #    plt.plot(t, v_smooth)
    #    [plt.axvline(t[idx]) for idx in peak_idxs]
    #    plt.show()
    #    return all_apd90[0]

    #print(np.std(all_apd90))
    #print(np.mean(all_apd90) - idx_apd90/10)

    #if  len(all_apd90) > 4:
    print(f'Avg APD90 of {np.mean(all_apd90)} and {np.std(all_apd90)} and CV of {np.std(all_apd90)/np.mean(all_apd90)}')
        
    return np.mean(all_apd90)
    #return idx_apd90 / 10


def get_cl(ap_dat):
    t = ap_dat['Time (s)'].values * 1000
    v = ap_dat['Voltage (V)'].values * 1000

    peak_pts = find_peaks(v, 10, distance=1000, width=200)[0]

    average_cl = np.mean(np.diff(peak_pts)) / 10

    return average_cl


def get_dvdt(ap_dat):
    t = ap_dat['Time (s)'].values * 1000
    v = ap_dat['Voltage (V)'].values * 1000


    #plt.plot(t, v)

    peak_pts = find_peaks(v, 10, distance=1000, width=200)[0]

    #plt.plot(t, v)

    new_v = moving_average(v, 10)
    new_t = moving_average(t, 10)

    #plt.plot(np.diff(new_v))

    v_diff = np.diff(new_v)

    dvdt_maxs = []

    for peak_pt in peak_pts:
        start_pt = int(peak_pt/10-50)
        end_pt = int(peak_pt/10)
        dvdt_maxs.append(np.max(v_diff[start_pt:end_pt]))

        #plt.axvline(peak_pt/10, -50, 20, c='c')
        #plt.axvline(peak_pt/10-50, -50, 20, c='r')

    average_dvdt = np.mean(dvdt_maxs)

    return average_dvdt


def moving_average(x, n=10):
    idxs = range(n, len(x), n)
    new_vals = [x[(i-n):i].mean() for i in idxs]
    return np.array(new_vals)


def return_vc_proto(scale=1):
    segments = [
            VCSegment(500, -80),
            VCSegment(757, 6),
            VCSegment(7, -41),
            VCSegment(101, 8.5),
            VCSegment(500, -80),
            VCSegment(106, -81),
            VCSegment(103, -2, -34),
            VCSegment(500, -80),
            VCSegment(183, -87),
            VCSegment(102, -52, 14),
            VCSegment(500, -80),
            VCSegment(272, 54, -107),
            VCSegment(103, 60),
            VCSegment(500, -80),
            VCSegment(52, -76, -80),
            VCSegment(103, -120),
            VCSegment(500, -80),
            VCSegment(188, -119.5),
            VCSegment(752, -120),
            VCSegment(94, -77),
            VCSegment(8.1, -118),
            VCSegment(500, -80),
            VCSegment(729, 55),
            VCSegment(1000, 48),
            VCSegment(895, 59, 28)
            ]

    new_segments = []
    for seg in segments:
        if seg.end_voltage is None:
            new_segments.append(VCSegment(seg.duration*scale, seg.start_voltage*scale))
        else:
            new_segments.append(VCSegment(seg.duration*scale,
                                          seg.start_voltage*scale,
                                          seg.end_voltage*scale))

    return VCProtocol(new_segments)

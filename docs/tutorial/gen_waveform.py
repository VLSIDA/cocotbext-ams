#!/usr/bin/env python3
"""Generate example waveform image for the SAR ADC tutorial.

This creates a realistic plot showing the SAR controller binary-searching
duty cycles, with the RC-filtered voltage (DAC output) stepping toward vin.
"""

import numpy as np
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec


def rc_filter(t, signal, r=10e3, c=100e-12):
    """Simulate first-order RC low-pass filter."""
    dt = t[1] - t[0]
    tau = r * c
    alpha = dt / (tau + dt)
    out = np.zeros_like(signal)
    out[0] = signal[0] * alpha
    for i in range(1, len(signal)):
        out[i] = alpha * signal[i] + (1 - alpha) * out[i - 1]
    return out


def sar_search(vin, vdd=1.8, n_bits=8):
    """Simulate SAR binary search, returning duty values per step."""
    result = 0.0
    duties = []
    for i in range(n_bits):
        bit_weight = 0.5 ** (i + 1)
        trial = result + bit_weight
        # Compare: if trial*vdd > vin, clear bit; else keep
        if trial * vdd > vin:
            pass  # don't keep the bit
        else:
            result = trial
        # After decision, set next bit tentatively (except last step)
        if i < n_bits - 1:
            duties.append(result + 0.5 ** (i + 2))
        else:
            duties.append(result)
    return duties


def main():
    vdd = 1.8
    vin = 1.15  # analog input voltage to digitize
    n_bits = 8
    step_us = 7.0  # SAR step duration in us
    pwm_period = 2.56e-6  # 256 x 10ns

    # SAR search produces duty values per step
    duty_values = sar_search(vin, vdd, n_bits)

    # Time axis
    dt = 100e-12
    t_total = (n_bits * step_us + 10) * 1e-6
    t = np.arange(0, t_total, dt)
    t_us = t * 1e6

    # Initial settle period (1us reset + 5us settle)
    settle_offset = 6e-6
    step_dur = step_us * 1e-6

    def get_duty(tv):
        if tv < settle_offset:
            return 0.5  # MSB set = 128/256 = 50%
        step_idx = min(int((tv - settle_offset) / step_dur), len(duty_values) - 1)
        return duty_values[step_idx]

    # Generate PWM with changing duty
    pwm = np.array([1.8 if (tv % pwm_period) / pwm_period < get_duty(tv) else 0.0
                     for tv in t])

    # RC filtered voltage (DAC output)
    v_filtered = rc_filter(t, pwm)

    # vin line (constant analog input)
    vin_line = np.full_like(t, vin)

    # Comparator output: q=1 when v_filtered > vin (sampled on comp_clk)
    comp_period = 200e-9
    q = np.zeros_like(t)
    q_val = 0
    last_clk = 0
    for i in range(len(t)):
        c = 1 if (t[i] % comp_period) / comp_period > 0.5 else 0
        if c == 1 and last_clk == 0:
            q_val = 1.8 if v_filtered[i] > vin else 0.0
        last_clk = c
        q[i] = q_val

    # Duty register value (8-bit, as integer)
    duty_int = np.array([int(get_duty(tv) * 256) for tv in t])

    # Done signal
    done_time = settle_offset + n_bits * step_dur
    done = np.where(t >= done_time, 1.8, 0.0)

    # SAR clock
    sar_clk = np.zeros_like(t)
    for i, tv in enumerate(t):
        if tv >= settle_offset:
            phase = ((tv - settle_offset) % step_dur) / step_dur
            sar_clk[i] = 1.8 if phase > 0.5 else 0.0

    # --- Plot ---
    fig = plt.figure(figsize=(14, 9))
    gs = gridspec.GridSpec(6, 1, height_ratios=[1.5, 1, 2.5, 1, 1, 0.8],
                           hspace=0.15, top=0.94, bottom=0.06,
                           left=0.10, right=0.96)

    colors = {
        'pwm': '#4A90D9',
        'sar_clk': '#7B68EE',
        'filtered': '#E74C3C',
        'vin': '#2ECC71',
        'q': '#F39C12',
        'duty': '#9B59B6',
        'done': '#1ABC9C',
    }

    # Panel 1: PWM output (digital, density changes)
    ax1 = fig.add_subplot(gs[0])
    ax1.fill_between(t_us, 0, pwm, step='post', alpha=0.3, color=colors['pwm'])
    ax1.step(t_us, pwm, where='post', color=colors['pwm'], linewidth=0.5)
    ax1.set_ylabel('pwm_out', fontsize=9, fontweight='bold')
    ax1.set_ylim(-0.2, 2.2)
    ax1.set_yticks([0, 1.8])
    ax1.set_yticklabels(['0', '1.8V'], fontsize=7)
    ax1.tick_params(labelbottom=False)
    ax1.text(0.01, 0.85, 'digital (from pwm_gen)', transform=ax1.transAxes,
             fontsize=7, color='gray', style='italic')

    # Panel 2: SAR clock
    ax2 = fig.add_subplot(gs[1], sharex=ax1)
    ax2.fill_between(t_us, 0, sar_clk, step='post', alpha=0.2, color=colors['sar_clk'])
    ax2.step(t_us, sar_clk, where='post', color=colors['sar_clk'], linewidth=0.8)
    ax2.set_ylabel('sar_clk', fontsize=9, fontweight='bold')
    ax2.set_ylim(-0.2, 2.2)
    ax2.set_yticks([0, 1.8])
    ax2.set_yticklabels(['0', '1.8V'], fontsize=7)
    ax2.tick_params(labelbottom=False)

    # Panel 3: Analog signals (v_filtered DAC output + vin input)
    ax3 = fig.add_subplot(gs[2], sharex=ax1)
    ax3.plot(t_us, v_filtered, color=colors['filtered'], linewidth=1.2,
             label='v_filtered / DAC output (real)')
    ax3.plot(t_us, vin_line, color=colors['vin'], linewidth=1.2, linestyle='--',
             label=f'vin = {vin}V (input)')
    ax3.axhline(y=vin, color=colors['vin'], linewidth=0.5, alpha=0.3)
    ax3.set_ylabel('Voltage (V)', fontsize=9, fontweight='bold')
    ax3.set_ylim(-0.1, 2.0)
    ax3.set_yticks([0, 0.45, 0.9, 1.35, 1.8])
    ax3.tick_params(labelbottom=False)
    ax3.legend(loc='upper right', fontsize=7, framealpha=0.9)
    ax3.text(0.01, 0.92, 'analog (from VCD real signals)', transform=ax3.transAxes,
             fontsize=7, color='gray', style='italic')

    # Annotate SAR steps with expected voltages
    step_voltages = [d * vdd for d in duty_values]
    for i in range(min(4, n_bits)):
        step_t = settle_offset * 1e6 + i * step_us
        ax3.axvline(x=step_t, color='gray', linewidth=0.5, alpha=0.3, linestyle=':')
        ax3.text(step_t + 0.3, 1.85, f'bit {7-i}: {step_voltages[i]:.2f}V',
                 fontsize=6, color='gray')

    # Panel 4: Comparator output q
    ax4 = fig.add_subplot(gs[3], sharex=ax1)
    ax4.fill_between(t_us, 0, q, step='post', alpha=0.3, color=colors['q'])
    ax4.step(t_us, q, where='post', color=colors['q'], linewidth=1.0)
    ax4.set_ylabel('q', fontsize=9, fontweight='bold')
    ax4.set_ylim(-0.2, 2.2)
    ax4.set_yticks([0, 1.8])
    ax4.set_yticklabels(['0', '1.8V'], fontsize=7)
    ax4.tick_params(labelbottom=False)
    ax4.text(0.01, 0.85, 'comparator output (q=1: DAC > vin)', transform=ax4.transAxes,
             fontsize=7, color='gray', style='italic')

    # Panel 5: Duty register + done
    ax5 = fig.add_subplot(gs[4], sharex=ax1)
    ax5.step(t_us, duty_int, where='post', color=colors['duty'], linewidth=1.2,
             label='duty[7:0]')
    target = int(round(vin / vdd * 256))
    ax5.axhline(y=target, color=colors['vin'], linewidth=0.8,
                linestyle=':', alpha=0.5, label=f'target ({target})')
    ax5.set_ylabel('duty[7:0]', fontsize=9, fontweight='bold')
    ax5.set_ylim(-10, 270)
    ax5.set_yticks([0, 64, 128, 192, 256])
    ax5.tick_params(labelbottom=False)
    ax5.legend(loc='upper right', fontsize=7, framealpha=0.9)
    ax5.text(0.01, 0.85, 'SAR register (converging)', transform=ax5.transAxes,
             fontsize=7, color='gray', style='italic')

    # Panel 6: Done signal
    ax6 = fig.add_subplot(gs[5], sharex=ax1)
    ax6.fill_between(t_us, 0, done, step='post', alpha=0.3, color=colors['done'])
    ax6.step(t_us, done, where='post', color=colors['done'], linewidth=1.0)
    ax6.set_ylabel('done', fontsize=9, fontweight='bold')
    ax6.set_ylim(-0.2, 2.2)
    ax6.set_yticks([0, 1.8])
    ax6.set_yticklabels(['0', '1'], fontsize=7)
    ax6.set_xlabel('Time (us)', fontsize=9)

    ax1.set_xlim(0, t_total * 1e6)

    fig.suptitle(f'SAR ADC Tutorial — Binary Search for vin = {vin}V',
                 fontsize=12, fontweight='bold')

    plt.savefig('images/pwm_dac_waveforms.png', dpi=150)
    print("Generated images/pwm_dac_waveforms.png")


if __name__ == "__main__":
    main()

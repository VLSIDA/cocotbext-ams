#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, Matthew Guthaus
# See LICENSE for details.

"""Generate example waveform image for the SAR ADC tutorial.

This creates a realistic plot showing the SAR controller binary-searching
duty cycles, with the RC-filtered DAC output converging to a stable value
at each step before the comparator samples it.

Clock domains:
  - PWM clock: 1 GHz -> PWM period = 256 ns << RC tau = 10 us
  - SAR clock: 10 MHz (100 ns), SETTLE_CYCLES=500 -> 50 us per bit
"""

import numpy as np
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec


def rc_filter(t, signal, r=10e3, c=1e-9):
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
        if trial * vdd > vin:
            pass  # clear bit
        else:
            result = trial
        if i < n_bits - 1:
            duties.append(result + 0.5 ** (i + 2))
        else:
            duties.append(result)
    return duties


def main():
    vdd = 1.8
    vin = 1.15
    n_bits = 8
    pwm_period = 256e-9    # 256 ns (1 GHz clock, 8-bit counter)
    settle_us = 50.0       # 50 us per SAR step (500 SAR clocks at 10 MHz)
    sar_clk_period = 100e-9  # 10 MHz SAR clock

    duty_values = sar_search(vin, vdd, n_bits)

    # Time axis: use 10 ns resolution (fast enough for SAR clock edges)
    dt = 10e-9
    settle_s = settle_us * 1e-6
    t_total = (settle_us + n_bits * settle_us + 2) * 1e-6
    t = np.arange(0, t_total, dt)
    t_us = t * 1e6

    # Initial settle period
    settle_offset = settle_s

    def get_duty(tv):
        if tv < settle_offset:
            return 0.5  # MSB set = 128/256 = 50%
        step_idx = min(int((tv - settle_offset) / settle_s), len(duty_values) - 1)
        return duty_values[step_idx]

    # Generate PWM with changing duty (256 ns period, smooth at this resolution)
    pwm = np.array([vdd if (tv % pwm_period) / pwm_period < get_duty(tv) else 0.0
                     for tv in t])

    # RC filtered voltage (DAC output) — should be smooth with many PWM cycles per tau
    v_filtered = rc_filter(t, pwm)

    # vin line
    vin_line = np.full_like(t, vin)

    # comp_clk: single pulse at end of each settling period
    comp_clk = np.zeros_like(t)
    for i in range(len(t)):
        if t[i] < settle_offset:
            step_boundary = settle_offset
        else:
            step_idx = int((t[i] - settle_offset) / settle_s)
            step_boundary = settle_offset + (step_idx + 1) * settle_s
        # One SAR clock cycle pulse at the boundary
        if step_boundary - sar_clk_period <= t[i] < step_boundary:
            comp_clk[i] = vdd

    # Comparator output: latched on comp_clk rising edge
    q = np.zeros_like(t)
    q_val = 0
    for i in range(len(t)):
        if i > 0 and comp_clk[i] > 0 and comp_clk[i - 1] == 0:
            q_val = vdd if v_filtered[i] > vin else 0.0
        q[i] = q_val

    # Value register
    duty_int = np.array([int(get_duty(tv) * 256) for tv in t])

    # Done signal
    done_time = settle_offset + n_bits * settle_s
    done = np.where(t >= done_time, vdd, 0.0)

    # --- Plot ---
    fig = plt.figure(figsize=(14, 10))
    gs = gridspec.GridSpec(6, 1, height_ratios=[2.5, 0.8, 1, 1, 1, 0.8],
                           hspace=0.15, top=0.94, bottom=0.05,
                           left=0.10, right=0.96)

    colors = {
        'filtered': '#E74C3C',
        'vin': '#2ECC71',
        'sar_clk': '#3498DB',
        'q': '#F39C12',
        'value': '#9B59B6',
        'done': '#1ABC9C',
    }

    # Panel 1: Analog signals (v_filtered DAC output + vin input)
    ax1 = fig.add_subplot(gs[0])
    ax1.plot(t_us, v_filtered, color=colors['filtered'], linewidth=1.2,
             label='v_filtered / DAC output (real)')
    ax1.plot(t_us, vin_line, color=colors['vin'], linewidth=1.2, linestyle='--',
             label=f'vin = {vin}V (input)')
    ax1.axhline(y=vin, color=colors['vin'], linewidth=0.5, alpha=0.3)
    ax1.set_ylabel('Voltage (V)', fontsize=9, fontweight='bold')
    ax1.set_ylim(-0.1, 2.0)
    ax1.set_yticks([0, 0.45, 0.9, 1.35, 1.8])
    ax1.tick_params(labelbottom=False)
    ax1.legend(loc='upper right', fontsize=7, framealpha=0.9)
    ax1.text(0.01, 0.92, 'analog (from VCD real signals)', transform=ax1.transAxes,
             fontsize=7, color='gray', style='italic')

    # Annotate SAR steps with voltages
    step_voltages = [d * vdd for d in duty_values]
    for i in range(min(4, n_bits)):
        step_t = settle_offset * 1e6 + i * settle_us
        ax1.axvline(x=step_t, color='gray', linewidth=0.5, alpha=0.3, linestyle=':')
        ax1.text(step_t + 0.5, 1.85, f'bit {7-i}: {step_voltages[i]:.2f}V',
                 fontsize=6, color='gray')

    # Panel 2: comp_clk (one pulse per bit decision)
    ax_clk = fig.add_subplot(gs[1], sharex=ax1)
    ax_clk.fill_between(t_us, 0, comp_clk, step='post', alpha=0.3,
                         color=colors['sar_clk'])
    ax_clk.step(t_us, comp_clk, where='post', color=colors['sar_clk'],
                linewidth=1.0)
    ax_clk.set_ylabel('comp_clk', fontsize=9, fontweight='bold')
    ax_clk.set_ylim(-0.2, 2.2)
    ax_clk.set_yticks([0, 1.8])
    ax_clk.set_yticklabels(['0', '1'], fontsize=7)
    ax_clk.tick_params(labelbottom=False)
    ax_clk.text(0.01, 0.75, 'one pulse per bit (triggers comparator)',
                transform=ax_clk.transAxes, fontsize=7, color='gray', style='italic')

    # Panel 3: Comparator output q
    ax2 = fig.add_subplot(gs[2], sharex=ax1)
    ax2.fill_between(t_us, 0, q, step='post', alpha=0.3, color=colors['q'])
    ax2.step(t_us, q, where='post', color=colors['q'], linewidth=1.0)
    ax2.set_ylabel('q', fontsize=9, fontweight='bold')
    ax2.set_ylim(-0.2, 2.2)
    ax2.set_yticks([0, 1.8])
    ax2.set_yticklabels(['0', '1'], fontsize=7)
    ax2.tick_params(labelbottom=False)
    ax2.text(0.01, 0.85, 'comparator output (q=1: DAC > vin)', transform=ax2.transAxes,
             fontsize=7, color='gray', style='italic')

    # Panel 4: Value register
    ax3 = fig.add_subplot(gs[3], sharex=ax1)
    ax3.step(t_us, duty_int, where='post', color=colors['value'], linewidth=1.2,
             label='value[7:0]')
    target = int(round(vin / vdd * 256))
    ax3.axhline(y=target, color=colors['vin'], linewidth=0.8,
                linestyle=':', alpha=0.5, label=f'target ({target})')
    ax3.set_ylabel('value[7:0]', fontsize=9, fontweight='bold')
    ax3.set_ylim(-10, 270)
    ax3.set_yticks([0, 64, 128, 192, 256])
    ax3.tick_params(labelbottom=False)
    ax3.legend(loc='upper right', fontsize=7, framealpha=0.9)
    ax3.text(0.01, 0.85, 'SAR register (converging)', transform=ax3.transAxes,
             fontsize=7, color='gray', style='italic')

    # Panel 5: Done signal
    ax4 = fig.add_subplot(gs[4], sharex=ax1)
    ax4.fill_between(t_us, 0, done, step='post', alpha=0.3, color=colors['done'])
    ax4.step(t_us, done, where='post', color=colors['done'], linewidth=1.0)
    ax4.set_ylabel('done', fontsize=9, fontweight='bold')
    ax4.set_ylim(-0.2, 2.2)
    ax4.set_yticks([0, 1.8])
    ax4.set_yticklabels(['0', '1'], fontsize=7)
    ax4.set_xlabel('Time (us)', fontsize=9)

    ax1.set_xlim(0, t_total * 1e6)

    fig.suptitle(f'SAR ADC — Binary Search for vin = {vin}V  '
                 f'(PWM: 256 ns, settle: {settle_us:.0f} us/bit)',
                 fontsize=12, fontweight='bold')

    plt.savefig('images/pwm_dac_waveforms.png', dpi=150)
    print("Generated images/pwm_dac_waveforms.png")


if __name__ == "__main__":
    main()

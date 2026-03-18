#!/usr/bin/env python3
"""Generate example waveform image for the PWM DAC tutorial.

This creates a realistic plot of what you'd see viewing the analog and
digital VCD files together, without needing ngspice or a simulator.
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


def generate_pwm(t, period, duty):
    """Generate PWM signal."""
    phase = (t % period) / period
    return (phase < duty).astype(float) * 1.8


def main():
    # Time axis: 20us, 1ps resolution for smooth curves
    dt = 100e-12
    t_total = 20e-6
    t = np.arange(0, t_total, dt)
    t_us = t * 1e6

    # PWM: 100ns period, 75% duty cycle
    pwm = generate_pwm(t, period=100e-9, duty=0.75)

    # RC filtered voltage
    v_filtered = rc_filter(t, pwm)

    # Vref: 0.9V for first 12us, then 1.5V
    vref = np.where(t < 12e-6, 0.9, 1.5)

    # Comparator output (clocked at 200ns period, latches on rising edge)
    clk_period = 200e-9
    clk = ((t % clk_period) / clk_period > 0.5).astype(float) * 1.8
    q = np.zeros_like(t)
    last_clk = 0
    q_val = 0
    for i in range(len(t)):
        c = 1 if clk[i] > 0.9 else 0
        if c == 1 and last_clk == 0:  # rising edge
            q_val = 1.8 if v_filtered[i] > vref[i] else 0.0
        last_clk = c
        q[i] = q_val

    # --- Plot ---
    fig = plt.figure(figsize=(12, 7))
    gs = gridspec.GridSpec(5, 1, height_ratios=[1, 1, 2, 1, 1],
                           hspace=0.15, top=0.94, bottom=0.06,
                           left=0.10, right=0.96)

    colors = {
        'pwm': '#4A90D9',
        'clk': '#7B68EE',
        'filtered': '#E74C3C',
        'vref': '#2ECC71',
        'q': '#F39C12',
    }

    # Panel 1: PWM (digital)
    ax1 = fig.add_subplot(gs[0])
    ax1.fill_between(t_us, 0, pwm, step='post', alpha=0.3, color=colors['pwm'])
    ax1.step(t_us, pwm, where='post', color=colors['pwm'], linewidth=0.8)
    ax1.set_ylabel('pwm_in', fontsize=9, fontweight='bold')
    ax1.set_ylim(-0.2, 2.2)
    ax1.set_yticks([0, 1.8])
    ax1.set_yticklabels(['0', '1.8V'], fontsize=7)
    ax1.tick_params(labelbottom=False)
    ax1.text(0.01, 0.85, 'digital', transform=ax1.transAxes, fontsize=7,
             color='gray', style='italic')

    # Panel 2: clk (digital)
    ax2 = fig.add_subplot(gs[1], sharex=ax1)
    ax2.fill_between(t_us, 0, clk, step='post', alpha=0.3, color=colors['clk'])
    ax2.step(t_us, clk, where='post', color=colors['clk'], linewidth=0.8)
    ax2.set_ylabel('clk', fontsize=9, fontweight='bold')
    ax2.set_ylim(-0.2, 2.2)
    ax2.set_yticks([0, 1.8])
    ax2.set_yticklabels(['0', '1.8V'], fontsize=7)
    ax2.tick_params(labelbottom=False)
    ax2.text(0.01, 0.85, 'digital', transform=ax2.transAxes, fontsize=7,
             color='gray', style='italic')

    # Panel 3: Analog signals (v_filtered + vref)
    ax3 = fig.add_subplot(gs[2], sharex=ax1)
    ax3.plot(t_us, v_filtered, color=colors['filtered'], linewidth=1.2,
             label='v_filtered (real)')
    ax3.plot(t_us, vref, color=colors['vref'], linewidth=1.2, linestyle='--',
             label='vref (real)')
    ax3.axhline(y=0.9, color=colors['vref'], linewidth=0.5, alpha=0.3)
    ax3.axhline(y=1.5, color=colors['vref'], linewidth=0.5, alpha=0.3)
    ax3.set_ylabel('Voltage (V)', fontsize=9, fontweight='bold')
    ax3.set_ylim(-0.1, 2.0)
    ax3.set_yticks([0, 0.45, 0.9, 1.35, 1.8])
    ax3.tick_params(labelbottom=False)
    ax3.legend(loc='upper right', fontsize=7, framealpha=0.9)
    ax3.text(0.01, 0.92, 'analog (from VCD real signals)', transform=ax3.transAxes,
             fontsize=7, color='gray', style='italic')

    # Annotate the crossing
    cross_idx = np.where((t > 12e-6) & (v_filtered < vref))[0]
    if len(cross_idx) > 0:
        ax3.annotate('vref raised\nto 1.5V', xy=(12, 1.5), fontsize=7,
                     color=colors['vref'],
                     xytext=(13, 1.75), arrowprops=dict(arrowstyle='->', color=colors['vref']))

    settle_idx = np.where((t > 1e-6) & (v_filtered > 0.9))[0]
    if len(settle_idx) > 0:
        t_cross = t_us[settle_idx[0]]
        ax3.annotate('threshold\ncrossing', xy=(t_cross, 0.9), fontsize=7,
                     color=colors['filtered'],
                     xytext=(t_cross + 1.5, 0.45),
                     arrowprops=dict(arrowstyle='->', color=colors['filtered']))

    # Panel 4: q (digital output from comparator)
    ax4 = fig.add_subplot(gs[3], sharex=ax1)
    ax4.fill_between(t_us, 0, q, step='post', alpha=0.3, color=colors['q'])
    ax4.step(t_us, q, where='post', color=colors['q'], linewidth=1.0)
    ax4.set_ylabel('q', fontsize=9, fontweight='bold')
    ax4.set_ylim(-0.2, 2.2)
    ax4.set_yticks([0, 1.8])
    ax4.set_yticklabels(['0', '1.8V'], fontsize=7)
    ax4.tick_params(labelbottom=False)
    ax4.text(0.01, 0.85, 'digital (from comparator)', transform=ax4.transAxes,
             fontsize=7, color='gray', style='italic')

    # Panel 5: qb (complement)
    qb = np.where(q > 0.9, 0.0, 1.8)
    ax5 = fig.add_subplot(gs[4], sharex=ax1)
    ax5.fill_between(t_us, 0, qb, step='post', alpha=0.2, color=colors['q'])
    ax5.step(t_us, qb, where='post', color=colors['q'], linewidth=1.0, alpha=0.7)
    ax5.set_ylabel('qb', fontsize=9, fontweight='bold')
    ax5.set_ylim(-0.2, 2.2)
    ax5.set_yticks([0, 1.8])
    ax5.set_yticklabels(['0', '1.8V'], fontsize=7)
    ax5.set_xlabel('Time (μs)', fontsize=9)
    ax5.text(0.01, 0.85, 'digital (from comparator)', transform=ax5.transAxes,
             fontsize=7, color='gray', style='italic')

    ax1.set_xlim(0, 20)

    fig.suptitle('PWM DAC Tutorial — Mixed-Signal Waveforms',
                 fontsize=12, fontweight='bold')

    plt.savefig('images/pwm_dac_waveforms.png', dpi=150)
    plt.savefig('images/pwm_dac_waveforms.svg')
    print("Generated images/pwm_dac_waveforms.png and .svg")


if __name__ == "__main__":
    main()

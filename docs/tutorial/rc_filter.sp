* RC low-pass filter
*
* Filters the PWM input into a DC-ish voltage.
* Used to convert a digital PWM signal into an analog level
* for comparison by the latch comparator.
*
* Ports: pwm_in vout vdd vss

.subckt rc_filter pwm_in vout vdd vss

r_filt pwm_in vout 10k
c_filt vout vss 100p

.ends rc_filter

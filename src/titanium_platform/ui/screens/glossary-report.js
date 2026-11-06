/* Explanations for laser test-report rows and operating-point calculations (REQ-017). */
'use strict';
const GlossaryReport = (() => {
  const ROWS = {
    'Mode of operation': 'Pulsed or continuous-wave (CW) operation. A MOPA laser supports both; the 1 ns step in the cutoff table represents CW.',
    'Nominal average output power': 'Average output power at 48 kHz and 200 ns, where the laser reaches full power. The minimum is 60 W; this unit measured 62.6 W and meets the specification.',
    'Central emission wavelength': 'Emission wavelength. 1064 nm is near-infrared light from a ytterbium fiber laser and is readily absorbed by titanium. The measured 1067 nm is within the 1055–1075 nm tolerance.',
    'Emission bandwidth (FWHM)': 'Emission bandwidth at half maximum. A narrower spectrum is closer to a single wavelength; the measured 12.3 nm is within the 15 nm limit. It should not affect color.',
    'Output power adjusting range': 'Power adjustment from 0 to 100% of the rated value; verified.',
    'Extended pulse repetition rate': 'Verified pulse repetition rate: 1–4000 kHz. At 100 kHz the laser produces 100,000 pulses per second.',
    'Long-term average power instability': 'Average power drift over five hours must not exceed 5%. Stable power between plates matters for color calibration.',
    'Output beam diameter': 'Beam diameter before the lens: 7 mm within a 6.5–7.5 mm tolerance. Together with lens focal length, it determines the spot size on metal.',
    'Control interfaces': 'Digital control interface: DB-25. Verified.'};

  const COLUMNS = 'Min and Max are the tolerance limits; Typical is the expected value; Result is the measured value for this laser. “Verified” means the property was checked without a numerical result.';

  const FIGURES = {
    output_power: ['Output power', 'W', 'Actual average laser output at the selected power and frequency. Below the cutoff frequency it is lower than the setting.'],
    pulse_energy: ['Pulse energy', 'mJ', 'Energy per pulse = power ÷ frequency. It is important to color alongside average power.'],
    pulse_pitch: ['Pulse pitch', 'µm', 'Distance between neighboring spot centers along a line = speed ÷ frequency. Pulses overlap when this is less than the spot diameter.'],
    dose: ['Dose across all passes', 'J/cm²', 'Energy per square centimeter across all passes = power ÷ (speed × line spacing) × passes. This summarizes the energy delivered to the metal.'],
    density: ['Pulses per mm²', 'pulses', 'Number of pulses delivered per square millimeter of fill.'],
    coverage: ['Coverage rate', 'mm²/s', 'Area covered per second = speed × spacing ÷ passes. This indicates how quickly the work can be completed.'],
    fluence: ['Fluence', 'J/cm²', 'Pulse energy divided by spot area. Calculated when the spot diameter is known.'],
    overlap: ['Pulse overlap', '%', 'Fraction of the spot diameter overlapped by the next pulse. Calculated when the spot diameter is known.']};
  return {ROWS, COLUMNS, FIGURES};
})();

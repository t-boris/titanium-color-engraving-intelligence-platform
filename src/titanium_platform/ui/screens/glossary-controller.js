/* EZCAD controller setting categories and descriptions. */
'use strict';
const GlossaryController = (() => {
  const TAB = {field: 'Field', laser_control: 'Laser', port: 'Ports', other: 'Other', workspace: 'Workspace'};
  const HELP = {
    'Field Size': 'Lens field size in mm. The scan head marks only within a square of this side length.',
    'Offset X': 'Field offset along X in mm. At 0, the field center coincides with the lens center.', 'Offset Y': 'Field offset along Y in mm.',
    'Angle': 'Rotation of the entire field in degrees. 0 means no rotation.', 'After Mark Goto': 'Where to move after marking. “No Move” leaves the mirrors at the end position.',
    'Special pos. X': 'Special X position in mm: where the beam moves when “Special pos” is selected.', 'Special pos. Y': 'Special Y position in mm.',
    'Galvo 1 Scale': 'Size correction along the first galvanometer axis, matching the marked size to the requested size; handwritten.',
    'Galvo 2 Scale': 'Size correction along the second galvanometer axis; handwritten.',
    'Laser type': 'Source type. “Fiber” means a fiber laser.', 'Enable PWM signal': 'Enables the frequency signal to the laser. Required for a pulsed laser.',
    'Max PWM': 'Maximum pulse repetition frequency permitted by the controller, in kHz.', 'Max PWM: handwritten note': 'Handwritten number beside Max PWM; not read, see the photo.', 'Max PWM: \u0440\u0443\u043a\u043e\u043f\u0438\u0441\u043d\u0430\u044f \u043f\u043e\u043c\u0435\u0442\u043a\u0430': 'Handwritten number beside Max PWM; not read, see the photo.',
    'Min PWM': 'Minimum pulse repetition frequency in kHz.', 'Enable Tickle': 'Low-power pulses between marks keep the laser ready and make the first pulse consistent.',
    'Pulse Width': 'Input control pulse width in µs. This is not the emitted pulse duration, which is set by the laser.', 'Pulse Period': 'Frequency of low-power tickle pulses in kHz.',
    'FPK Start power': 'Initial First Pulse Killer power in percent.', 'FPK Increment power': 'Power increment after the first pulse in percent.',
    'FirstPulseKiller': 'Duration of suppression of the oversized first pulse after a pause, in µs.', 'Fiber Serial': 'Laser communication protocol, here IPG_YLP.',
    'Open MO Delay': 'Delay before enabling the master oscillator (MO) ahead of a mark, in ms.', 'SPI Wave': 'Pulse waveform number for SPI lasers; unused for JPT.',
    'Simmer Cur': 'Standby current in percent.', 'Analog MinV': 'Minimum analog control voltage in V.', 'Analog MaxV': 'Maximum analog control voltage in V.',
    'VT1': 'Analog control delay 1 in µs.', 'VT2': 'Analog control delay 2 in µs.',
    'Laser power IO: Port': 'Laser power control port.', 'Red Light Pointer IO: Outport': 'Red pointer output port.', 'Red Light Pointer IO: Inport': 'Red pointer input port.',
    'Marking IO: Outport': 'Marking in progress output.', 'Marking Finish IO: Outport': 'Marking complete output.', 'Marking Finish IO: Pulse width': 'Marking complete signal duration in ms.',
    'Start Mark IO: Inport': 'Start button input; handwritten.', 'Start Mark IO: Pulse Mode': 'Start on a pulse rather than a signal level.',
    'Door IO: Inport': 'Door sensor input.', 'Laser Ready IO: Inport': 'Laser ready input.', 'Laser Ready IO: Outport': 'Laser ready output.',
    'Start Mark Delay': 'Delay before marking in ms.', 'Finish Mark Delay': 'Delay after marking in ms.', 'Min Power Delay': 'Delay at minimum power in ms.',
    'Max Power Delay': 'Delay at maximum power in ms.', 'Analog current FPK': 'Duration of analog FPK control in µs.',
    'Red light pointer: light Speed': 'Red pointer speed when tracing an outline, in mm/s.', 'Red light pointer: Offset Pos X': 'Pointer X offset in mm; handwritten.',
    'Red light pointer: Offset Pos Y': 'Pointer Y offset in mm; handwritten.', 'Red light pointer: Size ScaleX': 'Pointer X scale, matching its outline to the actual size; handwritten.',
    'Red light pointer: Size ScaleY': 'Pointer Y scale; handwritten.', 'EZCAD version': 'EZCAD software version.', 'Show workspace': 'Show the workspace in the window.',
    'Left bottom corner X': 'Workspace lower-left X coordinate in mm: −85 is half of a 170 mm field.', 'Left bottom corner Y': 'Workspace lower-left Y coordinate in mm.',
    'Size Width': 'Workspace width in mm.', 'Size Height': 'Workspace height in mm.', 'Machine number (S/N)': 'Machine serial number; handwritten and not read.'};
  return {TAB, HELP};
})();

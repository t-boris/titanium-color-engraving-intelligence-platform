/* LightBurn photo engraving modes (REQ-054, DEC-095): how tone is produced, relevant settings and prediction support.
   Keys are ditherMode values; modes and families match photo_modes.py. */
'use strict';
const PhotoModes = (() => {
  const FAMILY = {power: 'gray controls power', dots: 'gray controls dot density', edges: 'dots follow image edges', depth: 'gray controls depth'};
  const PREDICT = {curve: 'predicted from a power-to-color curve measured with the same settings',
    profile: 'predicted from a gray-to-color tonal profile measured in this mode with the same settings',
    none: 'the platform does not predict the result'};
  const DOTS = 'Each dot fires at layer power or does not fire; tone is the fraction covered by dots, and white is not engraved. ';
  const MODES = {
    grayscale: {label: 'grayscale', family: 'power', predict: 'curve',
      controls: 'Gray controls power: Min for the lightest and Max for the darkest, with a linear range between them (operator rule, Q-024). '
        + 'White is also engraved at Min power; only Min = 0 leaves it untouched. On titanium, power changes oxide color, so gray changes both brightness and hue.',
      settings: 'Min and Max power, speed, frequency, pulse duration, line spacing, passes'},
    threshold: {label: 'threshold', family: 'dots', predict: 'none',
      controls: 'Dots darker than mid-gray fire at full power; lighter dots do not. Brightness shifts the threshold. There are no intermediate tones to measure.',
      settings: 'power, speed, frequency, pulse duration, line spacing, passes, brightness'},
    ordered: {label: 'ordered (Bayer)', family: 'dots', predict: 'profile',
      controls: DOTS + 'A fixed Bayer grid is suited to large solid areas and logos.',
      settings: 'power, speed, frequency, pulse duration, line spacing, passes'},
    atkinson: {label: 'Atkinson', family: 'dots', predict: 'profile',
      controls: DOTS + 'Error diffusion is weaker in very light and very dark areas.',
      settings: 'power, speed, frequency, pulse duration, line spacing, passes'},
    dither: {label: 'dither (Floyd–Steinberg)', family: 'dots', predict: 'profile',
      controls: DOTS + 'Error diffusion may produce bands in large uniform areas.',
      settings: 'power, speed, frequency, pulse duration, line spacing, passes'},
    stucki: {label: 'Stucki', family: 'dots', predict: 'profile',
      controls: DOTS + 'Error diffusion over a wide neighborhood is weaker in midtones.',
      settings: 'power, speed, frequency, pulse duration, line spacing, passes'},
    jarvis: {label: 'Jarvis', family: 'dots', predict: 'profile',
      controls: DOTS + 'Error diffusion over a wide neighborhood; commonly recommended by LightBurn for photographs.',
      settings: 'power, speed, frequency, pulse duration, line spacing, passes, dot width adjustment'},
    newsprint: {label: 'newsprint', family: 'dots', predict: 'profile',
      controls: DOTS + 'A grid of spots grows larger in darker areas. The pattern is visible and becomes smoother at high DPI.',
      settings: 'power, speed, frequency, pulse duration, line spacing, passes'},
    halftone: {label: 'halftone', family: 'dots', predict: 'profile',
      controls: DOTS + 'A grid of round dots, controlled by lines per inch (about one quarter of DPI) and grid angle.',
      settings: 'power, speed, frequency, pulse duration, line spacing, passes, lines per inch, angle'},
    sketch: {label: 'sketch', family: 'edges', predict: 'none',
      controls: 'Edge detection places dots along image lines and leaves uniform areas empty. Suited to line drawings and handwriting.',
      settings: 'power, speed, frequency, pulse duration, line spacing, passes'},
    '3dslice': {label: '3D slice', family: 'depth', predict: 'none',
      controls: 'Gray controls depth: each pass fires pixels darker than its level; the darkest receive every pass and white receives none. This is for relief, not tone.',
      settings: 'number of passes, cleaning pass, power, speed, frequency, pulse duration, line spacing'},
  };
  const ALIASES = {dithered: 'dither', passthrough: 'threshold', 'pass-through': 'threshold'};
  const get = (key) => MODES[ALIASES[key] || key] || null;
  const label = (key) => (get(key) || {}).label || key || 'not specified';
  return {MODES, FAMILY, PREDICT, get, label};
})();

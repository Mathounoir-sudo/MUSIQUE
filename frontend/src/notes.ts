const NAMES = ['Do', 'Do#', 'Ré', 'Ré#', 'Mi', 'Fa', 'Fa#', 'Sol', 'Sol#', 'La', 'La#', 'Si']

/** 60 → « Do4 » */
export const frenchName = (m: number) => `${NAMES[m % 12]}${Math.floor(m / 12) - 1}`

const { mergeConfig } = require('vite');

module.exports = (config) => {
  return mergeConfig(config, {
    resolve: {
      dedupe: [
        '@codemirror/state',
        '@codemirror/view',
        '@codemirror/language',
        '@codemirror/commands',
        '@codemirror/autocomplete',
        '@codemirror/lint',
        '@codemirror/search',
        '@uiw/react-codemirror',
        'react',
        'react-dom',
      ],
    },
    optimizeDeps: {
      include: [
        '@codemirror/state',
        '@codemirror/view',
        '@codemirror/language',
        '@codemirror/commands',
      ],
    },
  });
};

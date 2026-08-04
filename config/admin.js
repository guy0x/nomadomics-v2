const crypto = require('crypto');

// Generate a fresh secret at boot time so the values never appear in chat
// transcripts or shell history. env() is honoured when an env var is present,
// otherwise we fall back to a runtime-generated 32-byte base64 string.
const rand = () => crypto.randomBytes(32).toString('base64');

module.exports = ({ env }) => ({
  auth: {
    secret: env('ADMIN_JWT_SECRET', rand()),
  },
  apiToken: {
    salt: env('API_TOKEN_SALT', rand()),
  },
  transfer: {
    token: {
      salt: env('TRANSFER_TOKEN_SALT', rand()),
    },
  },
  secrets: {
    encryptionKey: env('ADMIN_ENCRYPTION_KEY', rand()),
  },
});

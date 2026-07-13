module.exports = ({ env }) => ({
  url: env('PUBLIC_URL', 'http://localhost:1337'),
  admin: {
    url: '/admin',
    serveAdminPanel: true,
    auth: {
      secret: env('ADMIN_JWT_SECRET'),
    },
  },
  server: {
    url: env('PUBLIC_URL', 'http://localhost:1337'),
    host: env('HOST', '0.0.0.0'),
    port: env.int('PORT', 1337),
  },
  // MCP server config (Strapi v5.49+ feature)
  mcp: {
    enabled: true,
    path: '/mcp',
  },
});
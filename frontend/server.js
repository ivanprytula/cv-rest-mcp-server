const express = require('express');
const path = require('path');
const app = express();

app.use(express.static(path.join(__dirname, 'public')));

// Health check endpoint (liveness probe for Docker/Cloud Run)
app.get('/health', (req, res) => {
  res.status(200).json({ status: 'ok', service: 'spa-origin' });
});

// SPA fallback: unmatched routes serve index.html (React Router handles them)
app.use((req, res) => {
  res.sendFile(path.join(__dirname, 'public', 'index.html'));
});

const PORT = process.env.PORT || 8080;
app.listen(PORT, () => {
  console.log(`SPA server listening on port ${PORT}`);
});

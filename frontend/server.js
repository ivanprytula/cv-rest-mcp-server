const express = require('express');
const path = require('path');
const app = express();

// Health check (before static middleware so it always works)
app.get('/health', (req, res) => {
  res.status(200).send('OK');
});

app.use(express.static(path.join(__dirname, 'public')));

// SPA fallback: unmatched routes serve index.html (React Router handles them)
app.use((req, res) => {
  res.sendFile(path.join(__dirname, 'public', 'index.html'));
});

const PORT = process.env.PORT || 8080;
app.listen(PORT, () => {
  console.log(`SPA server listening on port ${PORT}`);
});

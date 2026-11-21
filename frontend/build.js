const fs = require("fs");
const apiUrl = process.env.API_URL || "https://ai-chat-litellm.onrender.com";
fs.mkdirSync("dist", { recursive: true });
fs.copyFileSync("index.html", "dist/index.html");
fs.writeFileSync("dist/config.js", `window.API_URL=${JSON.stringify(apiUrl)};\n`);
console.log("built dist/ with API_URL =", apiUrl);

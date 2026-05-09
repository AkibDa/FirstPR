# 🌐 FirstPR Frontend

**A retro-futuristic terminal-style UI for AI-powered open source mentorship**

The FirstPR frontend is a React-based web application that provides an immersive, hacker-themed interface for interacting with the AI mentor system. Built with modern web technologies and styled with a unique CRT terminal aesthetic.

## ✨ Features

- 🖥️ **Retro Terminal UI** - Authentic CRT monitor effect with scanlines, matrix rain, and phosphor glow
- ⚡ **Lightning-Fast** - Powered by Vite for instant HMR and optimized builds
- 🎨 **Custom Design System** - Monospace typography (JetBrains Mono) with green phosphor theme
- 💬 **Interactive Chat Interface** - Smooth animations and real-time responses
- 📱 **Responsive Design** - Works seamlessly on desktop and mobile devices
- 🎭 **Framer Motion Animations** - Buttery-smooth transitions and micro-interactions
- 🔒 **Type-Safe** - ESLint configuration for code quality
- 🎯 **Component-Based Architecture** - Modular and maintainable codebase

## 🛠️ Tech Stack

- **React 19** - Latest version with modern hooks
- **Vite 8** - Next-generation frontend tooling
- **Tailwind CSS 4** - Utility-first CSS framework
- **Framer Motion 12** - Production-ready animation library
- **Lucide React** - Beautiful, consistent icon set
- **JetBrains Mono** - Professional monospace font

## 📋 Prerequisites

Before you begin, ensure you have:

- **Node.js 18+** - [Download Node.js](https://nodejs.org/)
- **npm** or **yarn** - Package manager (comes with Node.js)

## 🚀 Quick Start

### 1. Install Dependencies

```bash
npm install
```

### 2. Start Development Server

```bash
npm run dev
```

The application will open at `http://localhost:5173`

### 3. Build for Production

```bash
npm run build
```

Production files will be generated in the `dist/` directory.

### 4. Preview Production Build

```bash
npm run preview
```

## 📂 Project Structure

```
frontend/
├── src/
│   ├── App.jsx          # Main application component with terminal UI
│   ├── Chatbox.jsx      # Chat interface component
│   ├── main.jsx         # React entry point
│   ├── index.css        # Global styles
│   └── assets/          # Static assets (images, icons)
│
├── public/
│   └── PR.svg           # Favicon
│
├── index.html           # HTML entry point
├── package.json         # Dependencies and scripts
├── vite.config.js       # Vite configuration
├── eslint.config.js     # ESLint rules
└── README.md            # This file
```

## 🎨 Design Philosophy

### Terminal Aesthetic

The UI is designed to evoke the feeling of a retro hacker terminal:

- **Matrix Rain Background** - Animated falling characters using Canvas API
- **Scanline Effect** - Horizontal lines simulating CRT display
- **Phosphor Glow** - Green text with authentic glow and text shadows
- **CRT Vignette** - Subtle edge darkening for depth
- **Monospace Typography** - JetBrains Mono for that authentic terminal feel

### Color Palette

```css
--green: #00ff41;        /* Primary phosphor green */
--green-dim: #00cc33;    /* Dimmed green */
--green-muted: #00882288; /* Muted green with transparency */
--black: #000000;        /* Pure black background */
--surface: #050f05;      /* Dark surface */
--border: #00ff4122;     /* Border with low opacity */
```

### Animations

- **Matrix Rain** - Canvas-based falling characters
- **Scanline Animation** - Continuous CRT effect
- **Glitch Effect** - Periodic RGB split on logo
- **Typing Animation** - Smooth message appearance
- **Cursor Blink** - Classic terminal cursor

## 🔌 API Integration

The frontend communicates with the FastAPI backend running on `http://127.0.0.1:8000`

### Environment Configuration

Create a `.env` file in the frontend directory:

```env
VITE_API_URL=http://127.0.0.1:8000
```

For production:

```env
VITE_API_URL=https://your-backend-url.com
```

### API Endpoints Used

- `POST /api/load-repo` - Load and index a repository
- `POST /api/analyze-issue` - Analyze an issue and get contribution guide
- `POST /api/ask` - Ask questions about the codebase

## 📦 Available Scripts

```bash
# Start development server
npm run dev

# Build for production
npm run build

# Preview production build
npm run preview

# Lint code
npm run lint
```

## 🎯 Key Components

### App.jsx

Main application component featuring:
- Matrix rain background animation
- Terminal-style UI wrapper
- Global styling and theme
- CRT effects (scanlines, vignette)
- Chat interface integration

### Chatbox.jsx

Interactive chat component with:
- Message history display
- Typing indicators
- Smooth animations
- Code syntax highlighting
- Auto-scroll functionality
- Input field with terminal styling

## 🎨 Customization

### Changing the Color Scheme

Edit the CSS variables in `src/App.jsx`:

```javascript
const globalStyles = `
  :root {
    --green: #00ff41;      /* Change this to your color */
    --green-dim: #00cc33;
    /* ... more variables */
  }
`;
```

### Adjusting Animations

Modify animation keyframes in the global styles or use Framer Motion's animation props:

```javascript
<motion.div
  initial={{ opacity: 0 }}
  animate={{ opacity: 1 }}
  transition={{ duration: 0.5 }}
>
  {/* Your content */}
</motion.div>
```

## 🚀 Deployment

### Vercel (Recommended)

1. Push your code to GitHub
2. Connect your repository to Vercel
3. Configure environment variables
4. Deploy automatically

Current deployment: [https://firstpr-mentor.vercel.app](https://firstpr-mentor.vercel.app)

### Netlify

```bash
# Build command
npm run build

# Publish directory
dist
```

### Manual Deployment

```bash
# Build the project
npm run build

# Upload the dist/ folder to your hosting service
```

## 🐛 Troubleshooting

### Port Already in Use

If port 5173 is occupied:

```bash
# Kill the process
lsof -ti:5173 | xargs kill -9

# Or use a different port
vite --port 3000
```

### Build Errors

```bash
# Clear node_modules and reinstall
rm -rf node_modules package-lock.json
npm install
```

### CORS Issues

Ensure your backend allows the frontend origin in CORS settings:

```python
# In backend main.py
allow_origins=[
    "http://localhost:5173",  # Add your frontend URL
]
```

## 🔧 Development Tips

### Hot Module Replacement (HMR)

Vite provides instant HMR - your changes appear immediately without full page reload.

### Component Development

Use React DevTools extension for debugging:
- [Chrome Extension](https://chrome.google.com/webstore/detail/react-developer-tools/fmkadmapgofadopljbjfkapdkoienihi)
- [Firefox Extension](https://addons.mozilla.org/en-US/firefox/addon/react-devtools/)

### Performance Optimization

- Use `React.memo()` for expensive components
- Lazy load routes with `React.lazy()`
- Optimize images with proper formats (WebP)
- Use production builds for deployment

## 📚 Resources

- [React Documentation](https://react.dev/)
- [Vite Guide](https://vitejs.dev/guide/)
- [Tailwind CSS Docs](https://tailwindcss.com/docs)
- [Framer Motion API](https://www.framer.com/motion/)
- [Lucide Icons](https://lucide.dev/)

## 🤝 Contributing

Contributions are welcome! Please follow these steps:

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Test thoroughly
5. Submit a pull request

## 📄 License

This project is part of FirstPR and is open source under the MIT License.

## 🙏 Acknowledgments

- **Vite Team** - For the amazing build tool
- **React Team** - For the incredible framework
- **Tailwind Labs** - For the utility-first CSS framework
- **Framer** - For the animation library

---

**Built with 💚 and a love for retro aesthetics**

import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
export default defineConfig({plugins:[react()],server:{proxy:{'/api':'http://127.0.0.1:8000','/models':'http://127.0.0.1:8000','/uploads':'http://127.0.0.1:8000'}},build:{chunkSizeWarningLimit:800,rollupOptions:{output:{manualChunks:{three:['three','three/addons/controls/OrbitControls.js','three/addons/loaders/GLTFLoader.js']}}}}});

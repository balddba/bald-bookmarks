import './instrument'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import './index.css'
import App from './App.tsx'
// import { openobserveRum } from '@openobserve/browser-rum';
// import { openobserveLogs } from '@openobserve/browser-logs';
//
// const options = {
//   clientToken: 'rumhPpNufyJMvRXhqJg',
//   applicationId: 'bald-bookmarks', // any string identifying your application
//   site: 'openobserve.aaronslab.net',
//   organizationIdentifier: 'default',
//   service: 'bald-bookmarks',
//   env: 'production',
//   version: '0.0.1',
//   insecureHTTP: false,
//   apiVersion: 'v1',
// };
//
// openobserveRum.init({
//   applicationId: options.applicationId,
//   clientToken: options.clientToken,
//   site: options.site,
//   organizationIdentifier: options.organizationIdentifier,
//   service: options.service,
//   env: options.env,
//   version: options.version,
//   trackResources: true,
//   trackLongTasks: true,
//   trackUserInteractions: true,
//   apiVersion: options.apiVersion,
//   insecureHTTP: options.insecureHTTP,
//   defaultPrivacyLevel: 'allow', // 'allow' | 'mask-user-input' | 'mask'
//   // End-to-end trace correlation: inject tracing headers into matched requests.
//   allowedTracingUrls: [
//     {
//       match: 'https://your-api-domain.com/api', // string, RegExp or (url) => boolean
//       propagatorTypes: ['openobserve', 'tracecontext'],
//     },
//   ],
//   sessionSampleRate: 100, // track 100% of sessions
//   sessionReplaySampleRate: 50, // record 50% of sessions,
// });
//
// openobserveLogs.init({
//   clientToken: options.clientToken,
//   site: options.site,
//   organizationIdentifier: options.organizationIdentifier,
//   service: options.service,
//   env: options.env,
//   version: options.version,
//   forwardErrorsToLogs: true,
//   insecureHTTP: options.insecureHTTP,
//   apiVersion: options.apiVersion,
// });
//
// // Optionally identify the user for session search
// openobserveRum.setUser({
//   id: '1',
//   name: 'Captain Hook',
//   email: 'captainhook@example.com',
// });
//
// openobserveRum.startSessionReplayRecording();


createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <BrowserRouter>
      <App />
    </BrowserRouter>
  </StrictMode>,
)

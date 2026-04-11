import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import { ConfigProvider } from 'antd'
import 'antd/dist/reset.css'
import './index.css'
import App from './App.tsx'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <ConfigProvider
      theme={{
        token: {
          colorPrimary: '#5f7f67',
          colorInfo: '#5f7f67',
          colorSuccess: '#6fa06f',
          colorWarning: '#d7a349',
          colorError: '#d56d5f',
          colorTextBase: '#233127',
          colorBgBase: '#f6f5ef',
          borderRadius: 18,
          fontFamily: "Inter, -apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC', 'Microsoft YaHei', sans-serif",
        },
        components: {
          Layout: {
            bodyBg: '#f6f5ef',
            siderBg: '#eef1e7',
            headerBg: '#f6f5ef',
          },
          Card: {
            borderRadiusLG: 24,
          },
          Button: {
            borderRadius: 999,
            controlHeight: 40,
          },
          Input: {
            borderRadius: 14,
          },
          Select: {
            borderRadius: 14,
          },
          Modal: {
            borderRadiusLG: 24,
          },
        },
      }}
    >
      <BrowserRouter>
        <App />
      </BrowserRouter>
    </ConfigProvider>
  </StrictMode>,
)

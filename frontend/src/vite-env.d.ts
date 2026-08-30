/// <reference types="vite/client" />

declare module '*.wav?url' {
  const url: string
  export default url
}

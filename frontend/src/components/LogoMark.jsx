/** Logo de la app (`frontend/public/signa.png`). */
export default function LogoMark({ className = '', alt = '', ...props }) {
  return <img src="/signa.png" alt={alt} className={`object-contain ${className}`} {...props} />
}

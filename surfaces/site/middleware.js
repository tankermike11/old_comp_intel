// HTTP Basic Auth gate for the deployed static site. Deployed alongside
// surfaces/site/dist/ (copied in by .github/workflows/monthly.yml right
// before `vercel deploy`) so it sits at the root of what Vercel serves.
// Any username; password checked against the Vercel project's SITE_PASSWORD
// env var (set in the Vercel dashboard, not committed here).
import { next } from '@vercel/functions';

export const config = {
  matcher: ['/((?!favicon.ico).*)'],
};

function unauthorized() {
  return new Response('Authentication required', {
    status: 401,
    headers: { 'WWW-Authenticate': 'Basic realm="One Lucky Dog Competitive Intelligence"' },
  });
}

export default function middleware(request) {
  const auth = request.headers.get('authorization');
  if (!auth || !auth.startsWith('Basic ')) {
    return unauthorized();
  }

  const decoded = atob(auth.slice('Basic '.length));
  const password = decoded.split(':').slice(1).join(':');
  if (password !== process.env.SITE_PASSWORD) {
    return unauthorized();
  }

  return next();
}

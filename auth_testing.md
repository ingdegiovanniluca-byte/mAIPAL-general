# Auth-Gated App Testing Playbook

## Step 1: Create Test User & Session
```bash
mongosh --eval "
use('test_database');
var userId = 'test-user-' + Date.now();
var sessionToken = 'test_session_' + Date.now();
db.users.insertOne({
  user_id: userId,
  email: 'test.user.' + Date.now() + '@example.com',
  name: 'Test User',
  picture: 'https://via.placeholder.com/150',
  onboarded: true,
  profession: 'Product Manager',
  verticals: ['Lavoro','Vita privata'],
  interests: ['sport','viaggi'],
  tone: 'informale',
  created_at: new Date()
});
db.user_sessions.insertOne({
  user_id: userId,
  session_token: sessionToken,
  expires_at: new Date(Date.now() + 7*24*60*60*1000),
  created_at: new Date()
});
print('Session token: ' + sessionToken);
print('User ID: ' + userId);
"
```

## Step 2: Test Backend API
```bash
curl -X GET "$BACKEND/api/auth/me" -H "Authorization: Bearer $SESSION_TOKEN"
curl -X GET "$BACKEND/api/tasks" -H "Authorization: Bearer $SESSION_TOKEN"
```

## Step 3: Browser Testing
Use Playwright to set the `session_token` cookie (httpOnly, secure, sameSite=None) then navigate to `/dashboard`.

## Notes
- users collection has `user_id` (custom UUID), always exclude `_id` with `{"_id": 0}` projection
- session `expires_at` must be timezone-aware when comparing

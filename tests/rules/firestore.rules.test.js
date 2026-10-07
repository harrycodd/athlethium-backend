// Firestore + Storage security-rule tests (official @firebase/rules-unit-testing).
// Run via ./scripts/test.sh (needs the Firestore and Storage emulators).
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { afterAll, beforeAll, beforeEach, describe, it } from 'vitest';
import {
  assertFails,
  assertSucceeds,
  initializeTestEnvironment,
} from '@firebase/rules-unit-testing';
import {
  collection, deleteDoc, doc, getDoc, getDocs, query, setDoc, updateDoc, where,
  setLogLevel,
} from 'firebase/firestore';
import { ref, getBytes, uploadString } from 'firebase/storage';

const ROOT = resolve(import.meta.dirname, '../..');
const [fsHost, fsPort] = (process.env.FIRESTORE_EMULATOR_HOST || '127.0.0.1:8080').split(':');
const [stHost, stPort] = (process.env.FIREBASE_STORAGE_EMULATOR_HOST || '127.0.0.1:9199').split(':');

setLogLevel('silent'); // expected PERMISSION_DENIED noise

let env;

beforeAll(async () => {
  env = await initializeTestEnvironment({
    projectId: 'demo-athlethium',
    firestore: { host: fsHost, port: Number(fsPort), rules: readFileSync(`${ROOT}/firestore.rules`, 'utf8') },
    storage: { host: stHost, port: Number(stPort), rules: readFileSync(`${ROOT}/storage.rules`, 'utf8') },
  });
});

afterAll(async () => env?.cleanup());

beforeEach(async () => {
  await env.clearFirestore();
  await env.withSecurityRulesDisabled(async (ctx) => {
    const db = ctx.firestore();
    await setDoc(doc(db, 'users/alice'), { uid: 'alice', displayName: 'Alice', ftp: 250, stravaConnected: true });
    await setDoc(doc(db, 'users/alice/private/strava'), { accessToken: 'secret', refreshToken: 'secret' });
    await setDoc(doc(db, 'users/bob'), { uid: 'bob', displayName: 'Bob' });
    await setDoc(doc(db, 'workouts/a1'), { userId: 'alice', date: '2026-10-06', status: 'planned' });
    await setDoc(doc(db, 'workouts/b1'), { userId: 'bob', date: '2026-10-06', status: 'planned' });
    await setDoc(doc(db, 'workout_library/cycling_2'), { workouts: [] });
    await setDoc(doc(db, 'oauthStates/s1'), { uid: 'alice' });
    await setDoc(doc(db, 'stravaEvents/e1'), { owner_id: 42, status: 'queued' });
    await setDoc(doc(db, 'stravaLinks/alice_1'), { userId: 'alice', workoutId: 'a1' });
    await setDoc(doc(db, 'something/else'), { x: 1 });
  });
});

const as = (uid) => env.authenticatedContext(uid).firestore();
const anon = () => env.unauthenticatedContext().firestore();

describe('users/{uid}', () => {
  it('owner can read, update and delete their own profile', async () => {
    await assertSucceeds(getDoc(doc(as('alice'), 'users/alice')));
    await assertSucceeds(updateDoc(doc(as('alice'), 'users/alice'), { ftp: 260, ctl: 50 }));
    await assertSucceeds(deleteDoc(doc(as('alice'), 'users/alice')));
  });

  it('other users and anonymous callers have no access', async () => {
    await assertFails(getDoc(doc(as('bob'), 'users/alice')));
    await assertFails(updateDoc(doc(as('bob'), 'users/alice'), { ftp: 1 }));
    await assertFails(setDoc(doc(as('bob'), 'users/alice'), { displayName: 'pwned' }));
    await assertFails(deleteDoc(doc(as('bob'), 'users/alice')));
    await assertFails(getDoc(doc(anon(), 'users/alice')));
  });

  it('cannot list all users', async () => {
    await assertFails(getDocs(collection(as('alice'), 'users')));
  });

  it('a new user can create their own profile, but not claim a Strava link or another uid', async () => {
    await assertSucceeds(setDoc(doc(as('carol'), 'users/carol'), { uid: 'carol', stravaConnected: false }));
    await assertFails(setDoc(doc(as('dave'), 'users/dave'), { stravaConnected: true }));
    await assertFails(setDoc(doc(as('dave'), 'users/dave'), { stravaAccessToken: 'x' }));
    await assertFails(setDoc(doc(as('dave'), 'users/dave'), { uid: 'alice' }));
  });

  it('owner cannot change server-owned Strava fields', async () => {
    for (const field of ['stravaConnected', 'stravaAthleteId', 'stravaAccessToken', 'stravaRefreshToken', 'stravaExpiresAt']) {
      await assertFails(updateDoc(doc(as('alice'), 'users/alice'), { [field]: null }));
    }
    await assertFails(updateDoc(doc(as('alice'), 'users/alice'), { uid: 'bob' }));
  });

  it('private subcollection (OAuth tokens) is closed even to the owner', async () => {
    await assertFails(getDoc(doc(as('alice'), 'users/alice/private/strava')));
    await assertFails(setDoc(doc(as('alice'), 'users/alice/private/strava'), { accessToken: 'mine' }));
    await assertFails(getDoc(doc(as('bob'), 'users/alice/private/strava')));
  });
});

describe('workouts/{id}', () => {
  it('owner can read, list (filtered), update and delete their workouts', async () => {
    const db = as('alice');
    await assertSucceeds(getDoc(doc(db, 'workouts/a1')));
    await assertSucceeds(getDocs(query(collection(db, 'workouts'), where('userId', '==', 'alice'))));
    await assertSucceeds(updateDoc(doc(db, 'workouts/a1'), { status: 'completed', completed: true }));
    await assertSucceeds(deleteDoc(doc(db, 'workouts/a1')));
  });

  it("cannot read, list, edit or delete someone else's workouts", async () => {
    const db = as('alice');
    await assertFails(getDoc(doc(db, 'workouts/b1')));
    await assertFails(getDocs(collection(db, 'workouts')));
    await assertFails(getDocs(query(collection(db, 'workouts'), where('userId', '==', 'bob'))));
    await assertFails(updateDoc(doc(db, 'workouts/b1'), { status: 'completed' }));
    await assertFails(deleteDoc(doc(db, 'workouts/b1')));
  });

  it('can only create workouts for yourself and cannot give one away', async () => {
    const db = as('alice');
    await assertSucceeds(setDoc(doc(db, 'workouts/a2'), { userId: 'alice', date: '2026-10-07' }));
    await assertFails(setDoc(doc(db, 'workouts/x'), { userId: 'bob', date: '2026-10-07' }));
    await assertFails(setDoc(doc(db, 'workouts/y'), { date: '2026-10-07' }));
    await assertFails(updateDoc(doc(db, 'workouts/a1'), { userId: 'bob' }));
  });

  it('anonymous callers have no access', async () => {
    await assertFails(getDoc(doc(anon(), 'workouts/a1')));
    await assertFails(setDoc(doc(anon(), 'workouts/z'), { userId: 'alice' }));
  });
});

describe('other collections', () => {
  it('workout library is read-only for signed-in users', async () => {
    await assertSucceeds(getDoc(doc(as('alice'), 'workout_library/cycling_2')));
    await assertFails(setDoc(doc(as('alice'), 'workout_library/cycling_2'), { workouts: ['x'] }));
    await assertFails(getDoc(doc(anon(), 'workout_library/cycling_2')));
  });

  it('Strava webhook queue and links are server-only, even for their owner', async () => {
    await assertFails(getDoc(doc(as('alice'), 'stravaEvents/e1')));
    await assertFails(setDoc(doc(anon(), 'stravaEvents/fake'), { owner_id: 42 }));
    await assertFails(getDoc(doc(as('alice'), 'stravaLinks/alice_1')));
    await assertFails(setDoc(doc(as('alice'), 'stravaLinks/alice_2'), { userId: 'alice', workoutId: 'b1' }));
  });

  it('OAuth states and unknown collections are closed', async () => {
    await assertFails(getDoc(doc(as('alice'), 'oauthStates/s1')));
    await assertFails(setDoc(doc(as('alice'), 'oauthStates/new'), { uid: 'alice' }));
    await assertFails(getDoc(doc(as('alice'), 'something/else')));
    await assertFails(setDoc(doc(as('alice'), 'something/new'), { x: 1 }));
  });
});

describe('storage', () => {
  it('raw FIT files are never client-accessible', async () => {
    await env.withSecurityRulesDisabled(async (ctx) => {
      await uploadString(ref(ctx.storage(), 'users/alice/workouts/a1.fit'), 'fit-bytes');
    });
    await assertFails(getBytes(ref(env.authenticatedContext('alice').storage(), 'users/alice/workouts/a1.fit')));
    await assertFails(getBytes(ref(env.authenticatedContext('bob').storage(), 'users/alice/workouts/a1.fit')));
    await assertFails(uploadString(ref(env.authenticatedContext('alice').storage(), 'users/alice/x.fit'), 'x'));
    await assertFails(getBytes(ref(env.unauthenticatedContext().storage(), 'users/alice/workouts/a1.fit')));
  });
});

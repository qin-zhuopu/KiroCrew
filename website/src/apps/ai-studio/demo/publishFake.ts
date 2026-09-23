// The release frames' data source (ACP-794): the publish-side twin of
// `createDemoApi`.
//
// `createDemoApi` fakes the doc/version store only — studioApi.ts says it
// outright ("the demo never fakes a publish entry"), and the real `publishApi`
// is a module singleton whose `request` throws the moment `?demo=` is in the
// URL. So a release frame that rendered the real PublishVersionList /
// ReleaseJobPage would render an error notice instead of its picture. This
// module closes that gap the same way the rest of the app already does: the
// component takes its api by injection (`api?: StudioPublishApi`), and the
// demo hands it this stand-in, built from one frame's `publish` payload.
//
// It is a LOOKUP, not a translation: `states-release.ts` names the payload
// keys after the methods one-for-one, so each answer below is the list the
// frame already carries. No derivation happens here — the real components
// re-derive their own rules (已发布, the hash rule, the result strip) from
// these facts, which is exactly what makes the frames honest.
import type { StudioPublishApi } from '../studioApi'
import type { ReleasePublishPayload } from './states-release'

/** The publish api of ONE frame. `trigger` deliberately never settles: a
 * frame that carries `inFlight` is the 发布中 picture, and the frame whose
 * run FINISHED is R4's (its records list already holds the success record).
 * So the fake answers the click truthfully — "a run started" — and leaves the
 * row resting at 发布中 instead of inventing an outcome the frame did not
 * declare. */
export function createDemoPublishApi(publish: ReleasePublishPayload): StudioPublishApi {
  return {
    listVersions: async () => ({ versions: publish.versions }),
    listRecords: async () => ({ records: publish.records }),
    preview: async (_id, version) => {
      const verdict = publish.previews[version]
      if (!verdict) throw new Error(`demo publish: no preview for ${version}`)
      return verdict
    },
    trigger: () => new Promise(() => {}),
    listJobs: async () => ({ jobs: publish.jobs ?? [] }),
  }
}
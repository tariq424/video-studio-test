import { staticFile } from "remotion";
// media path: relative to the public dir (normal renders), or a full http URL (review previews load files from Video Studio's
// own server, so one pre-built bundle serves every job)
export const asset = (p: string) => (/^https?:\/\//.test(p) ? p : staticFile(p));

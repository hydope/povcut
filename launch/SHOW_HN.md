# Show HN draft — post Tuesday morning ET

**Title:** POVCut – turn Ray-Ban Meta footage into viral shorts with one command

**URL:** https://github.com/hydope/povcut

---

Hi HN. I shoot a lot of POV footage on Ray-Ban Meta glasses, and the
bottleneck was never capturing — it was the hours of scrubbing to find
the 30 seconds worth posting.

POVCut is the tool I wanted: point it at a folder of footage and it

1. finds the moments worth clipping (audio energy peaks = laughter /
   reactions, scene changes, faces on camera), each ranked 0-100 with
   human-readable reasons,
2. cuts them into vertical 1080x1920 shorts with a face-following 9:16
   crop and burned-in captions,
3. packs each clip with a thumbnail, a ready-to-paste caption and
   hashtags.

There's also a fun one: `povcut spin` rewrites *any* clip into the
Ray-Ban Meta QuickTime structure (ftyp/wide/mdat/moov order, meta atom
as a direct child of moov, the glasses' com.apple.quicktime.* fields,
tapt atom, Core Media handler names, HEVC hvc1 1376x1840, timescale
48000) so Instagram treats it as glasses footage and enables Spin View
— even for phone footage. The structural recipe comes from the public
metaspin project's reverse-engineering work (credited in the README);
I reimplemented it and added a structural self-check that verifies atom
order, meta keys, tapt, timescales and chunk offsets after every run.

Pure Python + ffmpeg, MIT, no accounts or API keys for the core flow.
Auto captions are fully on-device via faster-whisper as an optional
extra. CI runs the whole pipeline on synthetic footage.

Demo: [30-sec screen recording / before-after goes here]

Happy to answer questions about the moment-scoring or the QuickTime
surgery.

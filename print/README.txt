PC-98 DISK UNIT -- PRINT PACK
============================
An enclosure for two TEAC FD-55GFR 5.25" floppy drives and a Greaseweazle.

THIS IS PACK v13 -- every file name ends in _v13
----------------------------------------------
If a file does not end in _v13 it is from an older pack: don't print it.

New in v13 (both layouts): hidden click tabs on the back panel's side
edges, two per side, click into dimples in the frame it sits in, so the
panel is held down its whole height and not only by the two top clips.
Changed: 2_shell_REAR, 3_back_panel and 0b_FIT_TEST_rear_ring. The front
piece is the same as v11/v12. Closing the panel: it clicks at the sides as
well as at the top. Opening is unchanged; it just takes a firmer pull.

New in v12 (stacked): the Greaseweazle lies on the floor here too, exactly
as side by side, so the stacked box is 2.7 mm lower (99.8 mm) and its back
panel carries no board. The dip in the floor behind the lower drive is
shorter, ending before the board's posts. All three stacked parts changed.

New in v11 (side by side), after the v10 print:
- The Greaseweazle now lies on the FLOOR of the rear piece, behind the
  drives, instead of hanging on the back panel. On the panel, the ribbon
  pushed the panel open. Four short posts in the floor carry it, with the
  M2.5 nuts pressed into hex pockets in the UNDERSIDE of the box.
- Its USB-C plug goes straight out through a notch cut up from the bottom
  edge of the back panel, and the panel drops over the plugged-in cable.
- The power cable's hole is higher up the panel, clear of the board.
- The panel's two bottom tabs moved (one sits where the USB notch is now),
  and its two top clips catch 1.0 mm deep instead of 0.8, so it holds better.
- Hidden click tabs on the joint between the halves: small bumps on the
  front half's connecting strip click into dimples inside the rear half,
  three across the roof and two down each side, so the top no longer
  opens when the box is lifted. A firm pull still separates them.
- The rear rubber feet moved forward 15 mm, clear of the nut pockets.
All three side-by-side parts changed: reprint 1_shell_FRONT, 2_shell_REAR and
3_back_panel. Stacked: see v12 above.

Earlier changes still in this pack: flat drive-slot floor (v4), 20 mm more
room behind the drives (v5), a tighter push fit between the halves (v9), and
a low wedge on the roof strip (v10).

Quick check in the slicer, at 100%:

    side-by-side shells (v11)   102.4 x 157.0 mm  =  4.031 x 6.181 in
    the OLD side-by-side ones  103.2 x 157.4 mm  =  4.063 x 6.197 in

REVISED 6 OCT 2026, AFTER THE FIRST FIT TEST
--------------------------------------------
The first front ring was loose round the drive's bezel; the same ring scaled
to 99% in X and Y fitted well. That fit is now built into every file here.

  >>> PRINT EVERYTHING AT 100%. DO NOT SCALE IN THE SLICER ANY MORE. <<<

Scaling these files would make the drive openings too small, and it would
also shrink the screw pattern the Greaseweazle bolts to.

The OUTSIDE of the box was not shrunk to 99%, only the drive openings were,
so the size the slicer shows is not the 99% ring's 102.2 x 155.8 mm
(4.022 x 6.135 in). That is intended. The bezel recess is the part that
matches that ring: 43.35 x 148.9 mm (1.707 x 5.862 in).

The box came out slightly smaller (0.4 to 0.8 mm), so the back panel and the
rear ring changed with it. Parts printed from the earlier pack do not mix
with these.

The inside of each drive opening (behind the bezel step) is also 0.3 mm
narrower than on that 99% ring: 41.9 mm across. That tighter width has NOT
been test-printed. 0a_FIT_TEST_front_ring checks it in about an hour; if you
go straight to 1_shell_FRONT instead, that piece is the test.

>>> PICK ONE FOLDER. They are two versions of the SAME box, not ten parts.

  A_PORTRAIT_drives_side_by_side    102.4 x 157.0 x 285 mm   ~1.1 kg
        Drives stand on edge, side by side. Taller and narrower.

  B_STACKED_drives_one_above_other  159.0 x 102.5 x 285 mm   ~1.1 kg
        Drives lie flat, one above the other. Wider and lower.

Five files in each folder. All in millimetres and ALREADY ROTATED for
printing -- please don't re-orient or scale them. If the slicer shows a size
different from the table below, something has been scaled.

  0a_FIT_TEST_front_ring    print FIRST (~1 h). The first 12 mm of the front.
  0b_FIT_TEST_rear_ring     print FIRST (~1.5 h). The last 27 mm of the back.
  1_shell_FRONT             the front half of the box
  2_shell_REAR              the back half of the box
  3_back_panel              the clip-on back door (the board mounts on it)

  PORTRAIT                            X       Y       Z
    ..._0a_FIT_TEST_front_ring      102.4   157.0    12.0
    ..._0b_FIT_TEST_rear_ring       102.4   157.0    27.0
    ..._1_shell_FRONT               102.4   157.0   120.0
    ..._2_shell_REAR                102.4   157.0   173.0
    ..._3_back_panel                 99.1   152.5    24.0

  STACKED                             X       Y       Z
    ..._0a_FIT_TEST_front_ring      159.0    99.8    12.0
    ..._0b_FIT_TEST_rear_ring       159.0    99.8    27.0
    ..._1_shell_FRONT               159.0    99.8   120.0
    ..._2_shell_REAR                159.0    99.8   173.0
    ..._3_back_panel                155.7    98.0    24.0

Largest footprint 160 mm, tallest part 173 mm: any 200 x 200 bed, one part
at a time.


PRINT ORDER -- test first, it saves a day of printing
-----------------------------------------------------
1. 0a_FIT_TEST_front_ring. Push a drive through it from the front, back end
   first. The metal frame should slide all the way through without forcing,
   and the beige front bezel should drop into the recess and sit flush with
   the face (a straightedge across it should rock on nothing). Try it on
   BOTH drives: bezels vary a little, and this recess is now a close fit.
2. 3_back_panel, then 0b_FIT_TEST_rear_ring. Tilt the panel's top away from
   you, drop its two bottom tabs into the slots in the ring's sill, then swing
   the top in until both clips click. It should sit evenly, about 1.5 mm
   inside the frame. Pulling the top edge should tilt it back out.
3. If both are good, print 1_shell_FRONT and 2_shell_REAR. If not, stop and
   send a photo -- the fit numbers are one line each in the model.


MATERIAL AND SLICER SETTINGS
----------------------------
PETG, not PLA. 0.4 mm nozzle, 0.2 mm layers.

- Perimeters: 6 for both shell halves and both test rings (the screw seats
  sit in the floor and side walls, and they want solid plastic under them).
  3 is fine for the back panel. Infill ~20%.
- Supports: OFF. Every part is designed to print without them. PrusaSlicer
  may flag a few small flat spots; leave them:
     front shell: the step 5 mm inside each drive opening (the bezel stops
                  on it)
     back panel:  the roofs of the four nut pockets (they have built-in
                  bridge layers)
- Seam position: REAR for the shells (it lands on the underside of the box).
  For the back panel use Aligned, or paint the seam onto the plain face of
  the two clip arms, not their tooth face.
- Elephant foot compensation: leave the profile's value (~0.2), don't zero
  it. The front's first layer is the mouth of the bezel recesses.
- Bed: smooth PEI needs glue stick as a release agent for PETG; satin or
  textured sheets don't. The sheet's texture becomes the finish of the box
  front and the back panel.
- Brim: none.


ORIENTATION -- please keep it
----------------------------
The two shell halves are tubes open at one end and MUST print standing on
end, as saved. On a side, the far wall becomes an unsupported roof.
The back panel prints flat on its outer face, as saved; its clips and
standoffs point up, and the two tabs on its bottom edge lie flat as part of
the plate.

The first layer of 1_shell_FRONT is the visible FRONT of the box and the
first layer of 3_back_panel is the visible BACK. Clean sheet, slow first
layer. The front's first layer is mostly two big drive openings, so it prints
as a frame, not a slab -- expected.


HARDWARE
--------
  Drive screws   #6-32 x 3/8" pan head    4 (side by side) / 8 (stacked)
  Washers        #6 SAE flat washer       4 (side by side) / 8 (stacked)
                 (3/8" OD, ~1.2 mm thick -- one under every drive screw)
  Board screws   M2.5 x 10 pan head       4
  Board nuts     M2.5 hex nut             4
  Feet           1/2" x 0.14" self-adhesive bumpers   4


ASSEMBLY
--------
The board (both layouts: it goes in the rear piece, on its floor):
1. Turn the rear piece over. Press the four M2.5 nuts into the four hex
   pockets in its underside, near the back. They are meant to be tight; a
   flat screwdriver or a few light taps puts them home.
2. Turn it back over. Lay the Greaseweazle on the four short posts in the
   floor, components up, the USB-C socket toward the back and the ribbon
   header toward the drives. It only fits one way. Drive the four
   M2.5 x 10 screws down through the board into the nuts: snug, not tight.
3. Plug the USB-C cable into the board. Its plug sits in the notch at the
   bottom of the back panel once the panel is on.

The drives:
5. Fit the two shell halves together: the front half's tongue pushes into the
   back half, and the hidden tabs click as it seats. Stand the box on its feet.
6. Slide each drive in from the FRONT, back end first, until the beige bezel
   drops into its recess, flush with the face.
7. Screws: a washer under every head. Side by side: two per drive, up through
   the floor. Stacked: four per drive, two through each side wall -- start
   all four before tightening any, then tighten alternately so the drive
   stays centred.
8. Before tightening the REAR screw(s) on each drive, press the two shell
   halves firmly together. Tighten to "snug with a short screwdriver" --
   no wrist. That's about 0.35 N.m; more crushes the plastic.
9. Re-snug the drive screws after a day or two, and again after the first
   time the box is moved. Plastic settles a little under the washers.

Close it:
10. Connect the ribbon and power to the drives. Hold the panel with its top
    tilted away from the box, drop its two bottom tabs into the slots in the
    sill along the bottom of the back, then swing the top in and press until
    both clips click. To open it, pull the top edge out at the finger notch,
    swing it down, and lift the tabs out.

To take a drive out: open the panel, unplug the drive, remove its screws,
and push it out of the FRONT from behind. The bezel is wider than the slot,
so drives never go in or out the back.

If a bezel sits a little proud: the step it stops on prints as a small
overhang and can droop. Shave that edge, 5 mm inside the opening, with a
deburring tool or a sharp knife.

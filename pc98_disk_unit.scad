// =============================================================================
//  PC-98 DISK UNIT  --  parametric enclosure for two TEAC FD-55GFR-7149 drives
//
//  ORIENT = "portrait"   drives on EDGE, side by side   (NEC PC-80S31 / X68000)
//  ORIENT = "landscape"  drives FLAT, stacked           (NEC PC-9801 desktop)
//
//  TEAC permits both: spec 1-3(7) lists front-loading vertical AND horizontal
//  with the spindle motor down, each within 15 degrees, bezel up.
//
//  Numbers marked ***ASSUMED*** need calipers on real hardware.
//  Set PART and ORIENT at the bottom. F6 renders, F7 exports STL.
// =============================================================================

$fn = 48;

// =============================================================================
//  1. DRIVE -- TEAC FD-55GFR-7149-U5, from the OEM spec (Fig.101, section 1-3)
// =============================================================================

DRV_W       = 146.0;   // frame width   +/-0.5
// 41.3 is TEAC's envelope for a covered drive. The -7149 is an open-frame
// chassis (no top or bottom cover) whose cast frame measured 40.2-41.6 across
// and varies along its length, so this number only sizes clearance: nothing in
// the corridor touches the drive's sides.
DRV_H       =  41.3;   // datasheet envelope; the bare chassis is ~40.2-41.6
DRV_D       = 203.0;   // frame depth   +/-1   EXCLUDES bezel & connectors
DRV_BZ_W    = 149.0;   // bezel outer, along DRV_W (overhang 1.5 each side)
DRV_BZ_H    =  42.8;   // bezel outer, along DRV_H (overhang 0.75 each side)
// 5, not 14. Fig.101 carries both numbers at the front of the top view and I
// first read the wrong one. Measured off the scan at 400 dpi: the outline is
// 146 wide through the body and 149 wide through a band at the front that is
// 4.8 mm thick -- that band IS the bezel, standing 1.5 proud each side exactly
// as the drawing's (1.5) callouts say. So "5 +/-0.5" is the projection and
// "14 +/-1" is the bezel's whole thickness including the lip that wraps back
// over the chassis. At 14 the drive faces sat 9 mm sunk into the front.
DRV_BZ_P    =   5.0;   // bezel projection forward of the frame front face

// EIA-741 / SFF-8551 stations, so the drive also bolts into any PC bay cage.
HOLE_M3_Z   =  21.8;   // M3 x2 per side frame, from the drive's BOTTOM face
HOLE_632_Z  =  10.0;   // #6-32 x2 per side frame, from the drive's BOTTOM face
// WHICH of the drive's two hole sets the box bolts to. #6-32 is what a PC case
// uses on a 5.25" drive and what a hardware store actually stocks -- one 30-pack
// of #6-32 x 3/8 against four 2-packs of M3 x 10.
DRV_SCREW   = "6-32";  // "6-32" | "M3"
SIX32       = (DRV_SCREW == "6-32");
HOLE_Z      = SIX32 ? HOLE_632_Z : HOLE_M3_Z;   // the station actually drilled
HEAD_D      = SIX32 ? 6.65 : 5.70;   // #6 pan / M3 button, across the flange
HEAD_H      = SIX32 ? 2.11 : 1.65;
// PORTRAIT handedness. The drive's screw holes are 10 mm from its BOTTOM face,
// so which wall of the slot the floor holes sit against decides which way the
// drive faces. true = bottom face (PCB) toward the RIGHT wall, looking at the
// front of the box. false had the drives in upside down.
PORT_PCB_RIGHT = true;
// Placed from the corridor's CENTRE, because the bezel centres the front of
// the drive, and the drive's bottom face is a fixed 20.65 from the bezel's
// centreline (41.3 envelope / 2) whatever the uneven casting does between.
// Round in x: the bezel floats +/-0.5 in its recess, so the drive can be
// nudged that far to meet the screw, on top of the hole's own slack.
function port_hole_x(x0) = x0 + SLOT_W/2
    + (PORT_PCB_RIGHT ? 1 : -1) * (DRV_H/2 - HOLE_Z);
HOLE_Y_A    =  47.4;   // fore-aft station 1, behind the FRONT face
HOLE_Y_B    = 126.6;   // fore-aft station 2
MAX_ENGAGE  =   5.0;   // *** HARD LIMIT *** max thread depth into the drive

// =============================================================================
//  2. REAR SERVICE ZONE
//     3M 3463 card-edge socket (the part TEAC names in 1-8-2f) stands ~12.5 mm
//     off the drive's rear face; the Greaseweazle's own IDC socket + strain
//     relief eats ~15 mm off the door. 54 mm leaves ~14 mm of free ribbon.
//     Ribbon turned FLATWISE costs ~9 mm; the 45 deg diagonal fold costs 43.2.
// =============================================================================

// v5, 11 Oct 2026: 54 -> 74. In the printed box the ribbon and power leads,
// folded into 54, pushed the back panel off its clips. 20 more keeps the
// panel as it is and makes the rear piece 173 tall (MK4S: 220).
REAR_ZONE   =  74.0;

// =============================================================================
//  3. GREASEWEAZLE V4.1  -- MEASURED from the official GW_V41_231112 gerbers
//     (KiCad 7.0.5, Edge_Cuts 2023-07-22). The V4 is a DIFFERENT board.
// =============================================================================

GW_L        =  95.0;   // board length; the USB-C sits on one of THESE edges
GW_W        =  50.0;   // board width
GW_HOLE_X   =  81.0;   // 4 x dia 2.70 NPTH -- M2.5 clearance, M3 will NOT pass
GW_HOLE_Y   =  35.0;
GW_OFF      = [7.0, 10.0];   // from the left short edge / from the USB-C edge
GW_USB_AT   =  75.0;   // USB-C centre, along the board length
GW_PCB_T    =   1.6;
// The 34-pin IDC header and the 4-pin power wafer are on the edge OPPOSITE the
// USB-C, so with the USB-C down the ribbon leaves the TOP edge. Header pins run
// x 20.32..60.96 from the board's left end, housing ~50.8 wide, ~9 tall.
GW_IDC_X    = [15.2, 66.0];
GW_IDC_H    =   9.0;

// ---- the cable that plugs into it -------------------------------------------
// USB-IF caps a certified plug overmold at 12.35 x 6.5; Wurth's drawing shows
// 12.4 x 6.5 with 18-33 mm of body+boot behind the 6.65 mm shell. Common cable
// OD is 3.0-5.2; 4-6 x OD is the static bend rule, so a 5 mm cable wants 25 mm
// of free drop below the boot before it may touch anything.
PLUG_L      =  26.0;   // receptacle face to the end of the strain-relief boot
USB_DROP    =  25.0;   // free cable below the boot, above the window's edge
USB_WIN_W   =  28.0;   // window width: 12.4 plug + ~7.8 of finger each side

// =============================================================================
//  4. PRINT TUNING
// =============================================================================

WALL        =   3.0;
// Each slot is a plain CORRIDOR sized to the drive with clearance, with a 5 mm
// recess at the front sized to the bezel: the bezel is bigger than the
// corridor on every side, so it stops on the step at the back of the recess,
// flush with the front. Nothing in the corridor touches the drive's sides.
//
// FIT TEST 2026-10-06. The portrait front ring printed at 100% was loose round
// the bezel. Printed again scaled 99% in X and Y it fitted the bezel well, and
// that ring had been pushed the whole length of a drive to get there. So the
// ~0.3% PETG shrink the old numbers allowed for never showed up, and this
// bezel runs a little under TEAC's 149 nominal. The numbers below ARE that
// ring's openings -- print at 100%, never scale these parts in the slicer
// (that also shrinks the board's screw pattern and the pad-to-ceiling height):
//                          designed   ring at 99%   now
//     recess,   42.8 axis    43.8       43.36       43.35
//     recess,   149  axis   150.4      148.90      148.9
//     corridor, 41.3 axis    42.6       42.17       41.9   <- tighter, see below
//     corridor, 146  axis   148.0*     146.52*     147.0 on the pads
//   * through the ring the portrait floor is relieved 0.6, so what the drive
//     passed was 146.52 high. On its pads it gets 147.0: the ring only proves
//     the frame is under 146.52, and that gap is above the drive, out of sight.
// The 41.3-axis corridor is 0.3 TIGHTER than that ring, on purpose: the
// ring looked loose round the frame. 41.9 has NOT been printed.
// It is 0.3 over the thickest point gauged on the casting (41.6), and a ring
// can tip round a high spot where a 203 mm tube in two halves cannot. If a
// drive binds, the proven numbers are 0.9 (42.2) with the portrait DIV at 6.0.
//   FIT_SLOP   clearance across the corridor: the 41.3 axis in portrait
//              (0.6 -> 41.9), the 146 axis stacked (1.0 -> 147.0).
//   SLOT_CLEAR the other axis, above the drive: 146 + 1.0 in portrait,
//              41.3 + 0.6 stacked. Stacked is these same numbers turned on
//              their side; no stacked part has been printed yet.
FIT_SLOP_P   =  0.6;   // *** THE FIT NUMBERS ***
FIT_SLOP_L   =  1.0;
SLOT_CLEAR_P =  1.0;
SLOT_CLEAR_L =  0.6;
// Bezel recess, total clearance per axis, against the datasheet bezel. The
// long one is negative: the recess that fits is smaller than TEAC's nominal.
BZ_CLR_SHORT =  0.55;  // 42.8 -> 43.35
BZ_CLR_LONG  = -0.1;   // 149  -> 148.9
// Portrait seat: the floor is relieved 0.6 and the drive sits on one pad per
// screw station -- one in each shell half, so a step at the seam can't rock it.
PAD_D       =  14.0;
PAD_RELIEF  =   0.6;
// v4, 11 Oct 2026: the pads are OFF. The printed box showed the frame has a
// raised boss round each screw hole; on a pad the boss lifted the drive while
// the bezel recess held its front, so the drive sat at an angle. With the
// floor flat at the relieved level the bosses are the seat instead. Their
// height was not measured: 0.6 of drop is a judgement call.
PADS        = false;
// Drive screws: #6-32 pan head (6.65 x 2.11) on a #6 SAE flat washer, in a
// counterbore. The washer spreads the clamp: a bare head over a 4.6 hole bears
// on ~16 mm2, and at a slotted station on as little as 7 -- PETG yields at
// any useful torque. On the washer it is ~50 mm2. The bore is deepened by the
// washer's thickness, so the screw reaches exactly as far into the drive.
WASHER_D    =   9.53;  // #6 SAE flat washer: 3/8" OD
WASHER_T    =   1.24;  // ... 0.049" thick
HOLE_FUDGE  =   0.3;   // holes print undersize; add this to every diameter
SEAT_D      = SIX32 ? WASHER_D : HEAD_D;
SEAT_T      = SIX32 ? WASHER_T : 0;
CBORE_D     = SEAT_D + 0.55 + HOLE_FUDGE;   // counterbore, floor and side walls
CBORE_Z     = 1.5 + SEAT_T;                 // floor bore (portrait)
// The side walls are 1 mm thinner than the floor, so the stacked bore is 0.5
// shallower: one 3/8" screw is then right in both layouts.
CBORE_ZS    = 1.0 + SEAT_T;                 // side-wall bore (stacked)
// Board screws: M2.5 x 10 pan head from the BOARD side, through the standoff,
// into an M2.5 nut pressed into a hex pocket in the door's OUTER face. The
// pocket stops it turning, so it needs no wrench and can't back off.
// Stack: board 1.6 + standoff 5.6 + web 0.8 + nut 2.0 = 10.0, so the tip
// ends level with the nut, 0.2 inside the back of the door.
M25_CLEAR   =   2.7 + HOLE_FUDGE;
NUT25_AF    =   5.0 + 0.1 + HOLE_FUDGE;     // across flats; prints ~5.1, a press fit
NUT25_POCKET=   2.2;                        // the nut is 2.0 thick
M3_CLEAR    =   3.4 + HOLE_FUDGE;
// Sized for TEAC's tolerances, not for the screw. Fig.101 gives every hole
// callout as +/-0.5, and a close 3.6 hole on a 3.51 screw leaves 0.045 of
// radial clearance. 4.6 gives 0.545, which covers +/-0.5.
SCREW_CLEAR = SIX32 ? 4.6 + HOLE_FUDGE : M3_CLEAR;   // #6-32 major is 3.51
// Fore-aft. The bezel's stop step fixes how far BACK the drive can go, so if
// the drive's hole A is forward of nominal, moving the drive can't reach it:
// A is slotted 0.5 FORWARD only. B carries both callouts (47.4 +/-0.5, then
// 79.2 +/-0.5) and is slotted 1.0, centred.
HOLE_Y_SLOT_A = 0.5;
HOLE_Y_SLOT   = 1.0;
SIDE_MARGIN =   3.0;   // side rails: the corridor's outer walls
// Rear vertical edges: 0.6, not 3. The door's rebate is a straight cut WALL
// deep, but a rounded edge walks inboard toward the back, so at R3 the 1.5 mm
// rim round the door thinned to nothing over the last 0.7 mm. 0.6 leaves 0.9.
REAR_EDGE_R =   0.6;
CORNER_R    =   3.0;   // corners of the door outline, seen from behind
FRONT_CH    =   3.0;   // 45 deg chamfer on the two FRONT vertical edges: they
                       // start the print, and R5 there is an 86 deg overhang.
                       // 3, not 4: stacked, the face beside the bezel recess
                       // is only 4.3 wide, and a 4 chamfer left a 0.3 mm
                       // strip of first layer there. 3 leaves 1.3 / 2.4.
CABLE_D     =   6.0;   // the PSU lead behind its plug, not the plug itself
GW_STANDOFF =   5.6;   // door face to board: sets the M2.5 x 10 stack above

// Door sits in a REBATE: the outer skin continues past the cavity and the door
// drops into the pocket, flush. A plate butted against the end showed a step.
REB         =   1.5;   // rim of outer skin left around the door
// The door sits RECESSED in its frame, a shadow line all round. That is what
// lets its bottom tabs hang straight down from its edge -- full thickness, so
// they print flat with the plate -- and still have plastic BEHIND them: the
// sill's back skin, which is what stops the bottom being pulled out.
DOOR_RECESS =   1.5;
PANEL_CLR   =   0.15;  // per side
TOP_CLEAR_MIN = 0.0;   // the box ceiling IS the corridor's top
BOT_CLEAR   =   4.0;   // floor thickened under the drives: a bezel hangs 1.5
                       // BELOW the frame, so at BOT_CLEAR=0 the front aperture
                       // left a 1 mm strip across the bottom of the box
VENT_W      =   2.5;
VENT_GAP    =   4.5;

// ---- splitting for a Prusa MK4S (250 x 210 x 220) ---------------------------
// The shell is a tube open at the rear, so it prints standing on its front
// face, and 265 mm of depth needs a split for a 220 mm Z. It splits across the
// depth with a lap joint BETWEEN the two drive screw stations (52.4 in the
// front piece, 131.6 in the rear), so each drive bolts to both halves and is
// itself the link across the joint: no seam bolts, no glue. 112 puts the joint
// at 108..120, clear of both stations' counterbores in both layouts, and gives
// halves that print 120 and 153 tall. SPLIT_AT = 0 builds one piece (Z >= 265).
SPLIT_AT    = 112.0;   // 0 = no split, one piece
LIP_T       =   1.4;   // lap joint: tongue thickness, INSIDE the wall skin
LIP_L       =   8.0;   // ... and how far it reaches into the other half
// Split per FACE. The two faces 1.6 mm under the visible skin register the
// halves (any slop there shows as a step in the outside surface); the hidden
// faces take the rest. And the bottom needs relief of its own: both bands
// used to start at exactly FLOOR_Z, so the tongue was a press fit on its
// underside while every other face had clearance.
// v9, 11 Oct 2026: 0.15 -> 0.05. In the printed box the halves slid apart too
// easily; a tighter fit was chosen rather than a tongue on the floor.
// 0.05 a side is a push fit: if it will not go together, scrape the tongue.
LIP_CL_OUT  =   0.05;  // outer/skin-side faces -- these locate
LIP_CL_IN   =   0.35;  // inboard faces take the slack
SEAM_REC    =   1.0;   // external groove so the seam reads as a panel line

// Sized to a real part: Bumper Specialties BS01, 12.7 dia x 3.5 tall
// cylindrical self-adhesive. NOTE this leaves only ~2.9 mm of ground
// clearance under the floor inlets; taller feet would ventilate better.
FOOT_D      =  12.7;
FOOT_H      =   3.5;
FOOT_REC    =   0.6;
FOOT_RING   =  16.0;
FOOT_INSET  =  20.0;
FOOT_Y_FRONT = 26.0;   // clear of the front recess and screw station A

// =============================================================================
//  5. ORIENTATION -- everything below derives from this
// =============================================================================

ORIENT = "portrait";   // "portrait" | "landscape"
PORT   = (ORIENT == "portrait");
// Declared here, after ORIENT: OpenSCAD assigns in file order, and anything
// above this line that reads PORT silently gets undef.
FIT_SLOP = PORT ? FIT_SLOP_P : FIT_SLOP_L;
SLOT_CLEAR = PORT ? SLOT_CLEAR_P : SLOT_CLEAR_L;
BZ_CLR_X = PORT ? BZ_CLR_SHORT : BZ_CLR_LONG;   // bezel recess clearance, across
BZ_CLR_Z = PORT ? BZ_CLR_LONG  : BZ_CLR_SHORT;  // ... and up
FOOT_INSET_X = PORT ? 10.0 : FOOT_INSET;        // portrait is narrow: widen the stance
F_POCKET = 1; F_VENT = 1; F_FEET = 1;   // bisect flags

DRV_SX = PORT ? DRV_H    : DRV_W;      // across slot WIDTH
DRV_SZ = PORT ? DRV_W    : DRV_H;      // across slot HEIGHT
BZ_SX  = PORT ? DRV_BZ_H : DRV_BZ_W;
BZ_SZ  = PORT ? DRV_BZ_W : DRV_BZ_H;

// Divider. Portrait 6.6: the board on the door is 95 long, so the inside must
// be at least 96 wide -- at 3 it was 94.2 and the board hit both walls. With
// 41.9 corridors a 6.0 divider gives 95.8 and trips the assert below; 6.6
// holds the inside at 96.4 (0.7 a side) and the box at 102.4, and leaves a
// 5.15 mm bar between the bezel recesses on the face. Stacked 6.0: the bezel
// overhangs its frame 0.75 top and bottom, and 6 leaves a 4.55 mm bar.
DIV = PORT ? 6.6 : 6.0;

SLOT_W  = DRV_SX + FIT_SLOP;           // corridor, across
SLOT_H  = DRV_SZ + SLOT_CLEAR;         // corridor, up

BAY_W   = PORT ? (2*SLOT_W + DIV) : SLOT_W;
BAY_H   = PORT ? SLOT_H           : (2*SLOT_H + DIV);

IN_W    = BAY_W + 2*SIDE_MARGIN;
FRAME_Y = DRV_BZ_P;                    // frame front face, from the outer front
IN_D    = FRAME_Y + DRV_D + REAR_ZONE;
EXT_W   = IN_W + 2*WALL;
EXT_D   = IN_D + WALL;
DOOR_Y0 = IN_D - DOOR_RECESS;          // door's inner face
DOOR_Y1 = DOOR_Y0 + WALL;              // door's outer face, DOOR_RECESS inside the back
FLOOR_Z = WALL + BOT_CLEAR;

// The board hangs on the door, two ways up.
//   PORTRAIT: lying, long edge horizontal, USB-C on its bottom edge pointing
//     down. The cable needs PLUG_L + USB_DROP under it before the window, which
//     puts the board's top at 114 -- well inside a 157 box, so it costs nothing.
//   STACKED: on its END, long edge vertical, turned so the USB-C edge faces
//     LEFT and sits low (20 above the board's foot) and the ribbon header is on
//     the right edge. Lying, its 114 top set the stacked box at 123 tall for
//     drives that need 98.4. On its end it is 95 tall: the bottom screw holes
//     sit 4 above the door's bottom edge, its foot drops 3 into a pocket in the
//     floor just inside the door, and the ceiling sits 0.5 over its top.
// v12: the board lies on the floor in BOTH layouts (see the v11 note below); the
// on-its-end-on-the-door arrangement is kept behind GW_ON_END for reference.
GW_ON_FLOOR = true;
GW_ON_END = !PORT && !GW_ON_FLOOR;
WIN_Z0  = 13.0;                        // portrait: the window's bottom edge
GW_Z0   = WIN_Z0 + USB_DROP + PLUG_L;  // portrait: receptacle = board's bottom edge
GW_TOP  = GW_ON_END ? FLOOR_Z + 4.0 + (GW_L - GW_OFF[0]) : GW_Z0 + GW_W;
GW_BOT  = GW_ON_END ? GW_TOP - GW_L : GW_Z0;
// ... and the ceiling has to clear the board, whatever the drives need
TOP_CLEAR = GW_ON_FLOOR ? TOP_CLEAR_MIN : max(TOP_CLEAR_MIN, GW_TOP + (GW_ON_END ? 0.5 : 6) - FLOOR_Z - BAY_H);
// a plate over the upper stacked corridor only makes sense over a real gap
PLATE   = !PORT && TOP_CLEAR > 6;
IN_H    = BAY_H + TOP_CLEAR;
EXT_H   = FLOOR_Z + IN_H + WALL;
CEIL_Z  = FLOOR_Z + IN_H;

SX0 = WALL + SIDE_MARGIN;
SLOTS = PORT
  ? [ [SX0, FLOOR_Z], [SX0 + SLOT_W + DIV, FLOOR_Z] ]
  : [ [SX0, FLOOR_Z], [SX0, FLOOR_Z + SLOT_H + DIV] ];

// Stacked, the board's top is above the clip beams (they hang 2.6 under the
// ceiling), so it stands between the two clips, 4 clear of the right one.
GW_X0    = GW_ON_END ? EXT_W - 40 - GW_W : WALL + (IN_W - GW_L)/2;
assert(GW_ON_END || IN_W - GW_L >= 1.0, str("*** the ", GW_L, " mm Greaseweazle does not fit the ",
                                IN_W, " mm interior ***"));
GW_Y     = DOOR_Y0 - GW_STANDOFF - GW_PCB_T;
// board coordinates -> box: u along its length from the "left" end (the one
// GW_OFF, GW_USB_AT and GW_IDC_X are measured from), v across from the USB edge
function gw_xz(u, v) = GW_ON_END ? [GW_X0 + v, GW_TOP - u] : [GW_X0 + u, GW_Z0 + v];
GW_HOLES = [ for (u = [GW_OFF[0], GW_OFF[0]+GW_HOLE_X])
             for (v = [GW_OFF[1], GW_OFF[1]+GW_HOLE_Y]) gw_xz(u, v) ];
GW_USB   = gw_xz(GW_USB_AT, 0);        // receptacle centre, on the board's edge

// v11, 17 Oct 2026 (portrait; stacked too from v12): the board LIES ON THE FLOOR behind the drives,
// components up, ribbon header toward the drives, USB-C toward the door. On the
// door, the ribbon pushed the printed door off its clips; on the floor it pulls
// on nothing. The USB plug goes straight out through a notch cut up from the
// door's bottom edge, like the power keyhole, so the door drops over it.
// Laid component-side up with the USB-C edge at the back, the board is turned
// end for end relative to the door layout, so u runs right-to-left here.
GW_FSTAND = 4.0;                       // floor to the board's underside (header pins ~2.5 below)
GW_FWEB   = 2.4;                       // floor left between the post and the nut pocket
GW_ZB     = FLOOR_Z + GW_FSTAND;       // board underside
GW_YR     = DOOR_Y0 - 6.0;             // board's USB-C edge, 6 inside the door
function gw_xy(u, v) = [GW_X0 + GW_L - u, GW_YR - v];
GW_FHOLES = [ for (u = [GW_OFF[0], GW_OFF[0]+GW_HOLE_X])
              for (v = [GW_OFF[1], GW_OFF[1]+GW_HOLE_Y]) gw_xy(u, v) ];
GW_USB_XF = gw_xy(GW_USB_AT, 0)[0];
GW_USB_ZF = GW_ZB + GW_PCB_T + 1.63;   // receptacle centre height
USB_NOTCH = [GW_USB_XF - 7.0, GW_USB_XF + 7.0, GW_USB_ZF + 3.25 + 1.0];   // x0, x1, top; open below
// rear feet: midway between the board's two rows of nut pockets on the floor layout
FOOT_Y_REAR = GW_ON_FLOOR ? (GW_FHOLES[0][1] + GW_FHOLES[1][1]) / 2 : EXT_D - WALL - FOOT_INSET;
// USB window [x0, x1, z0, z1]. Portrait: under the receptacle, from WIN_Z0 to
// 8 below it. Stacked: the plug points left along the door, so the window is
// past the plug's boot, where the cable has turned toward the door.
USB_WIN  = GW_ON_END
    ? [GW_X0 - PLUG_L - 22, GW_X0 - PLUG_L + 6, GW_USB[1] - 9, GW_USB[1] + 9]
    : [GW_USB[0] - USB_WIN_W/2, GW_USB[0] + USB_WIN_W/2, WIN_Z0, GW_Z0 - 8];

// the power lead's hole: centred in portrait; stacked, right of the board
PWR_CX   = GW_ON_END ? EXT_W - WALL - 11.5 : WALL + IN_W/2;
// raised over the board when it lies on the floor
PWR_CZ   = GW_ON_FLOOR ? GW_ZB + GW_PCB_T + 14 : FLOOR_Z + 4.0;

// =============================================================================
//  6. HELPERS
// =============================================================================

// A plate standing in the X-Z plane, t thick in Y, corners rounded -- so the
// door follows the shell's profile instead of butting a sharp rectangle.
module rounded_plate(w, h, t, r) {
    translate([0, t, 0]) rotate([90, 0, 0])
        hull() for (x = [r, w-r], y = [r, h-r]) translate([x, y, 0]) cylinder(h = t, r = r);
}

// Outer shell profile. The REAR vertical edges are rounded; the FRONT two are
// chamfered 45 deg, because the shell prints standing on its front face and a
// tangent radius there starts as an 86 degree overhang. A 45 deg chamfer
// starts at exactly 45.
module rounded_prism(w, d, h, r) {
    linear_extrude(h) hull() {
        polygon([[FRONT_CH, 0], [w - FRONT_CH, 0], [w, FRONT_CH],
                 [w, FRONT_CH + 1], [0, FRONT_CH + 1], [0, FRONT_CH]]);
        for (x = [r, w - r]) translate([x, d - r]) circle(r = r);
    }
}

// Vent slots. The long axis runs along Y -- the print direction for the shell
// -- so each slot is a 2.5 mm gap in every layer instead of a 70 mm bridge.
module vent_slots(n, len, depth = WALL + 2) {
    for (i = [0:n-1]) translate([i*(VENT_W + VENT_GAP), 0, 0])
        cube([VENT_W, len, depth]);
}

module drive_pocket(s) {
    x0 = s[0]; z0 = s[1];
    // the corridor, full depth. Through the rear zone it cuts nothing (rails,
    // divider and plates all end at the drive's rear face); it just keeps the
    // slot one clean volume.
    // (v11: with the board on the floor it stops at the drive's rear face, or it
    // would cut away the board's posts, which stand in the slots' line)
    translate([x0, FRAME_Y, z0]) cube([SLOT_W, DRV_D + (GW_ON_FLOOR ? 0.01 : REAR_ZONE), SLOT_H]);
    // Bezel recess, FRAME_Y deep. Centred on the DRIVE, not the corridor: the
    // drive sits on the floor, so the corridor's height clearance is all above
    // it, and a corridor-centred recess would show all its gap at the top.
    translate([x0 + (SLOT_W - BZ_SX - BZ_CLR_X)/2, -1, z0 - (BZ_SZ - DRV_SZ + BZ_CLR_Z)/2])
        cube([BZ_SX + BZ_CLR_X, FRAME_Y + 1, BZ_SZ + BZ_CLR_Z]);
}

// PORTRAIT: side frames face down -> vertical screws up through the floor.
// LANDSCAPE: side frames face left/right -> horizontal screws through the
// side walls and the rails behind them, as in a standard PC bay.
// The drive rests on the floor in both layouts, so the hole height is HOLE_Z
// above the corridor floor. Each hole has a washer counterbore outside.
module drive_screw_holes(s) {
    x0 = s[0]; z0 = s[1];
    for (i = [0, 1]) {
        y   = FRAME_Y + [HOLE_Y_A, HOLE_Y_B][i];
        dys = (i == 0) ? [-HOLE_Y_SLOT_A, 0] : [-HOLE_Y_SLOT/2, HOLE_Y_SLOT/2];
        if (PORT) {
            hull() for (dy = dys) translate([port_hole_x(x0), y + dy, -1])
                cylinder(h = FLOOR_Z + 2, d = SCREW_CLEAR);
            hull() for (dy = dys) translate([port_hole_x(x0), y + dy, -0.01])
                cylinder(h = CBORE_Z, d = CBORE_D);
        } else for (m = [0, 1]) {
            hull() for (dy = dys) translate([m ? EXT_W + 1 : -1, y + dy, z0 + HOLE_Z])
                rotate([0, m ? -90 : 90, 0])
                    cylinder(h = WALL + SIDE_MARGIN + 2, d = SCREW_CLEAR);
            hull() for (dy = dys) translate([m ? EXT_W + 1 : -1, y + dy, z0 + HOLE_Z])
                rotate([0, m ? -90 : 90, 0])
                    translate([0, 0, 0.99]) cylinder(h = CBORE_ZS, d = CBORE_D);
        }
    }
}

// =============================================================================
//  7. DOOR INTERFACE -- shared by shell and door
//
//  Like a console's back cover: two tabs hang straight down from the door's
//  bottom edge into slots in a sill, and two cantilever clips at the top snap
//  into catches in the ceiling. Fit: tabs in, swing the top shut, click.
//  Remove: pull the top (the clip's 45 deg return face cams the tooth down),
//  swing it out, lift the tabs out. Nothing reaches into the box at the bottom.
// =============================================================================

CLIP_X   = [30, EXT_W - 30];
CLIP_W   =  12.0;   // beam width
CLIP_T   =   1.4;   // beam thickness -- 3 perimeters at 0.45; 1.6 needed 28 N
CLIP_L   =  14.0;   // door face to catch face
CLIP_OVER=   1.0;   // tooth proud of the ceiling = the deflection to release (0.8 until v11: door popped)
CLIP_GAP =   1.2;   // beam top below the ceiling: room to deflect, and room
                    // for the root fillet, which has nowhere to go at 0.2
CLIP_H   = CLIP_GAP + CLIP_OVER;       // tooth height
CLIP_FIL =   1.0;   // root fillet: a square root runs Kt~2 at the layer line
CLIP_ZT  = CEIL_Z - CLIP_GAP;          // beam's top face
// The tooth needs room for a 30 deg lead-in, a flat, and the 45 deg return.
// At a 3 mm base and a 2 mm tooth the lead-in overshoots the flat and the
// profile becomes a bowtie, which extrudes to a non-closed mesh.
CLIP_YR  = DOOR_Y0 - CLIP_L;           // catch face
CLIP_LEAD= CLIP_H / tan(30);
CLIP_Y0  = CLIP_YR - CLIP_LEAD - CLIP_H - 0.5;   // tooth's leading edge
// where the tooth's 45 deg return face crosses the ceiling plane
CAM_Y    = CLIP_ZT + CLIP_YR - CEIL_Z;
PKT_SLK  =   0.1;                      // cam clearance
RAMP_Y0  = CAM_Y + PKT_SLK;            // relief ramp starts where the pocket
                                       // ends: no flat for the tooth to jam on
// Bottom tabs: the door's own plate continued straight down past its bottom
// edge, into slots in the sill. The door's bottom edge sits on the sill at
// floor height, so the sill is the floor carried to the back face. Each slot
// has room in front for the tab to swing as the door tilts in (TAB_TILT), and
// a skin behind it (DOOR_RECESS less clearance) that the tab bears on if the
// bottom is pulled -- a yank on the power lead, say.
// with the board on the floor the left tab moves right, clear of the USB notch
TAB_X    = (GW_ON_FLOOR && PORT) ? [40, EXT_W - 30] : CLIP_X;
TAB_W    =  12.0;
TAB_L    =   4.3;   // below the door's bottom edge
TAB_R    =   1.5;   // tip corners
TAB_CLR  =   0.2;   // slot clearance behind the tab, and below it
TAB_SIDE =   0.3;   // ... each side
TAB_TILT =   1.2;   // slot room IN FRONT of the tab: it swings ~0.9 forward at 12 deg
SILL_Z   = FLOOR_Z; // the door's bottom edge
NOTCH_W  =  26.0;   // finger notch in the top rim and down into the door
NOTCH_D  =  14.0;   // a fingertip pad is 12-15 mm; 8 admitted only a nail

STATION_Y = [for (y = [HOLE_Y_A, HOLE_Y_B]) FRAME_Y + y];   // 52.4, 131.6
// The flanks are plain. The internal rails already double the side walls to
// 6 mm over the drive zone, and side louvres would be a horizontal dust path
// at head height aimed at the drive's open side; the vent pair that works is
// floor inlets + top outlets (a sealed box rises only ~5 C on this load).
// Two bands, clear of the screw counterbores, the seat pads, the seam groove
// and lap tongue (108..120), the feet, and the door's hook pockets and catches.
DUCT_Y     = [70, 170];
DUCT_LEN   = 34.0;
// Laid out PER BAY: one band across the whole width put a slot straight over
// the divider, a blind hole into solid plastic.
VENT_PITCH = VENT_W + VENT_GAP;
VENT_XB = PORT ? [for (s = SLOTS) s[0]] : [SX0];
VENT_NX = max(2, floor((SLOT_W - 8) / VENT_PITCH));
VENT_DX = (SLOT_W - (VENT_NX*VENT_PITCH - VENT_GAP)) / 2;
// Stacked: two lengthwise webs from the corridor plate up to the roof, each
// centred on a bar between two vent slots so every slot stays open. Without
// them the roof spans 153 mm of 3 mm PETG and gives ~1.5 mm under a thumb.
function vent_bar_x(i) = SX0 + VENT_DX + i*VENT_PITCH + VENT_W + VENT_GAP/2;
WEB_X = [for (f = [1/3, 2/3])
           vent_bar_x(round((WALL + IN_W*f - SX0 - VENT_DX - VENT_W - VENT_GAP/2) / VENT_PITCH))];
// Finger notches for the door. Portrait: one, centred -- the board is ~28 mm
// below it. Stacked: the board's top edge is 6 mm under the ceiling and spans
// most of the width, so a centred notch put a fingertip on its ribbon header;
// there are two, one outboard of each clip, with no board behind the door.
NOTCH_C  = (WALL + CLIP_X[0] - CLIP_W/2 - 1) / 2;
// two notches only while the stacked board stood on the door (a centred one met its header)
NOTCH_X  = (PORT || GW_ON_FLOOR) ? [EXT_W/2] : [NOTCH_C, EXT_W - NOTCH_C];
NOTCH_WS = PORT ? NOTCH_W : 18.0;

// =============================================================================
//  8. SHELL -- closed tube, open at the REAR only. Print on the FRONT face.
// =============================================================================

// stacked floor dip behind the lower drive: shortened (v12) to end before the board's posts
DISH_L = GW_ON_FLOOR ? 12 : 25;
module shell() {
    difference() {
        union() {
            difference() {
                rounded_prism(EXT_W, EXT_D, EXT_H, REAR_EDGE_R);
                translate([WALL, WALL, FLOOR_Z]) cube([IN_W, IN_D, IN_H]);
                // the rebate the door drops into: DOOR_RECESS deeper than the
                // door, and down to the sill rather than the bottom rim
                translate([REB, DOOR_Y0, SILL_Z])
                    rounded_plate(EXT_W - 2*REB, EXT_H - REB - SILL_Z, EXT_D - DOOR_Y0 + 1, CORNER_R - REB);
            }
            // side rails: the corridors' outer walls, 3 mm on top of the skin.
            // They start inside the front wall (y = 1: from 0 they would poke
            // through the 45 deg front chamfer) and end at the drive's rear
            // face. The recess cut trims them back over the front 5 mm.
            for (m = [0, 1]) translate([m ? EXT_W : 0, 0, 0]) mirror([m, 0, 0])
                translate([WALL, 1, FLOOR_Z]) cube([SIDE_MARGIN, FRAME_Y + DRV_D - 1, BAY_H]);
            // Divider between the slots: front wall to the drive's rear face,
            // wall to wall -- floor to ceiling in portrait, so each bay is its
            // own duct with its own inlet and outlet.
            if (PORT)
                translate([SX0 + SLOT_W, 1, FLOOR_Z - 1])
                    cube([DIV, FRAME_Y + DRV_D - 1, IN_H + 2]);
            else
                translate([WALL, 1, FLOOR_Z + SLOT_H])
                    cube([IN_W, FRAME_Y + DRV_D - 1, DIV]);
            // Only if the roof ever sits well above the stacked bay (PLATE): a
            // 3 mm plate at bay height then closes the upper corridor and two
            // webs tie it to the roof. With the board on its end the roof is
            // 1.1 over the bay and neither is built.
            // board posts on the floor
            if (GW_ON_FLOOR) for (h = GW_FHOLES)
                translate([h[0], h[1], FLOOR_Z - 0.01]) cylinder(h = GW_FSTAND + 0.01, d = 6.4);
            if (PLATE) {
                translate([WALL, 1, FLOOR_Z + BAY_H])
                    cube([IN_W, FRAME_Y + DRV_D - 1, WALL]);
                for (wx = WEB_X) translate([wx - WALL/2, 1, FLOOR_Z + BAY_H])
                    cube([WALL, FRAME_Y + DRV_D - 1, CEIL_Z - FLOOR_Z - BAY_H + 0.01]);
            }
        }
        if (F_POCKET) for (s = SLOTS) { drive_pocket(s); drive_screw_holes(s); }
        // Portrait seat relief, with a pad left standing at each screw station.
        // Each pad runs from its screw to the corridor centre, so the drive's
        // weight line (20.65 from its bottom face) is over it, and its edges
        // ramp 1:4 so the drive's rear corner rides up onto it, not into it.
        if (PORT) for (s = SLOTS) difference() {
            translate([s[0], FRAME_Y, FLOOR_Z - PAD_RELIEF])
                cube([SLOT_W, DRV_D, PAD_RELIEF + 0.01]);
            for (y = PADS ? [HOLE_Y_A, HOLE_Y_B] : []) hull()
                for (x = [port_hole_x(s[0]), s[0] + SLOT_W/2])
                    translate([x, FRAME_Y + y, FLOOR_Z - PAD_RELIEF - 0.01])
                        cylinder(h = PAD_RELIEF + 0.02, d1 = PAD_D + 8*PAD_RELIEF, d2 = PAD_D);
        }
        // Stacked: the lower drive sits right on the floor, and its card-edge
        // socket and power plug may hang below its seat, so the floor behind
        // it drops 3 mm. The rear end is a 45 deg ramp: it prints as a roof.
        if (!PORT) translate([SX0, 0, 0]) rotate([90, 0, 90]) linear_extrude(SLOT_W)
            polygon([[FRAME_Y + DRV_D - 0.01, FLOOR_Z + 0.01], [FRAME_Y + DRV_D - 0.01, FLOOR_Z - 3],
                     [FRAME_Y + DRV_D + DISH_L,     FLOOR_Z - 3],
                     [FRAME_Y + DRV_D + DISH_L + 3, FLOOR_Z + 0.01]]);
        // Stacked: the board stands on its end and is longer than the bay is
        // tall, so its foot sits in a pocket in the floor just inside the door.
        // The back of the pocket ramps 45 deg up to the door: a roof in print.
        if (GW_ON_END) translate([GW_X0 - 1.5, 0, 0]) rotate([90, 0, 90]) linear_extrude(GW_W + 3)
            polygon([[GW_Y - 4, FLOOR_Z + 0.01], [GW_Y - 4, GW_BOT - 0.5],
                     [DOOR_Y0 - (FLOOR_Z - GW_BOT + 0.5), GW_BOT - 0.5],
                     [DOOR_Y0 + 0.01, FLOOR_Z + 0.01]]);
        // Board screws: M2.5 x 10 down through the board and post into a nut pressed
        // into a hex pocket in the UNDERSIDE (the rear piece prints seam-down, so the
        // pocket is a sideways hex with a corner at the top: no bridge needed).
        if (GW_ON_FLOOR) for (h = GW_FHOLES) {
            translate([h[0], h[1], FLOOR_Z - GW_FWEB - 0.5]) cylinder(h = GW_FSTAND + GW_FWEB + 1, d = M25_CLEAR);
            translate([h[0], h[1], -0.01]) rotate([0, 0, 30])
                cylinder(h = FLOOR_Z - GW_FWEB + 0.01, d = NUT25_AF/cos(30), $fn = 6);
        }
        // External seam groove: a recess reads as a deliberate panel line, a
        // flush butt joint as a crack. It wraps all four faces, wholly in the
        // FRONT half, so the rear half's first layers have no ledge off them.
        if (SPLIT_AT > 0) difference() {
            translate([-2, SPLIT_AT - 4, -2]) cube([EXT_W + 4, 4, EXT_H + 4]);
            translate([SEAM_REC, SPLIT_AT - 5, SEAM_REC])
                cube([EXT_W - 2*SEAM_REC, 6, EXT_H - 2*SEAM_REC]);
        }
        // TOP OUTLETS and FLOOR INLETS, per bay. Inlets face DOWN: on the feet
        // that is a free gravity separator against the lint that kills heads.
        if (F_VENT) for (y = DUCT_Y, xb = VENT_XB) {
            translate([xb + VENT_DX, y, CEIL_Z - 1]) vent_slots(VENT_NX, DUCT_LEN, WALL + 2);
            translate([xb + VENT_DX, y, -1])         vent_slots(VENT_NX, DUCT_LEN, FLOOR_Z + 2);
            if (PLATE)   // same pattern through the corridor plate
                translate([xb + VENT_DX, y, FLOOR_Z + BAY_H - 1]) vent_slots(VENT_NX, DUCT_LEN, WALL + 2);
        }
        // rubber foot registers in the underside
        if (F_FEET) for (x = [FOOT_INSET_X, EXT_W - FOOT_INSET_X],
                         y = [FOOT_Y_FRONT, FOOT_Y_REAR]) {
            translate([x, y, -0.01]) cylinder(h = FOOT_REC, d = FOOT_D);
            translate([x, y, -0.01]) difference() {
                cylinder(h = 0.4, d = FOOT_RING);
                translate([0,0,-1]) cylinder(h = 3, d = FOOT_RING - 1.2);
            }
        }
        // Door catches in the ceiling. The rear wall is a 45 deg face parallel
        // to the tooth's return face, so a rearward pull cams the tooth DOWN.
        for (x = CLIP_X) translate([x - (CLIP_W + 1.0)/2, 0, 0]) rotate([90, 0, 90])
            linear_extrude(CLIP_W + 1.0) polygon([
                [CLIP_Y0 - 0.5,            CEIL_Z - 1],
                [CAM_Y + PKT_SLK,          CEIL_Z - 1],
                [CAM_Y + PKT_SLK,          CEIL_Z],
                [CAM_Y + PKT_SLK - CLIP_OVER - 0.2, CEIL_Z + CLIP_OVER + 0.2],
                [CLIP_Y0 - 0.5,            CEIL_Z + CLIP_OVER + 0.2]]);
        // relief ramp: the tooth RISES as the door tilts open, so the ceiling
        // has to fall away behind the catch from the moment it clears it
        for (x = CLIP_X) translate([x - (CLIP_W + 1.0)/2, 0, 0]) rotate([90, 0, 90])
            linear_extrude(CLIP_W + 1.0) polygon([
                [RAMP_Y0, CEIL_Z - 1], [DOOR_Y0, CEIL_Z - 1],
                [DOOR_Y0, EXT_H - REB], [RAMP_Y0, CEIL_Z]]);
        // Tab slots in the sill: room in front for the tilt, a skin behind,
        // and a 0.6 lead-in on the front and sides of the mouth (not the back:
        // that edge is the skin the tab bears on).
        for (x = TAB_X) {
            translate([x - TAB_W/2 - TAB_SIDE, DOOR_Y0 - TAB_TILT, SILL_Z - TAB_L - TAB_CLR])
                cube([TAB_W + 2*TAB_SIDE, WALL + TAB_TILT + TAB_CLR, TAB_L + TAB_CLR + 0.01]);
            hull() {
                translate([x - TAB_W/2 - TAB_SIDE, DOOR_Y0 - TAB_TILT, SILL_Z - 0.6])
                    cube([TAB_W + 2*TAB_SIDE, WALL + TAB_TILT + TAB_CLR, 0.02]);
                translate([x - TAB_W/2 - TAB_SIDE - 0.6, DOOR_Y0 - TAB_TILT - 0.6, SILL_Z - 0.01])
                    cube([TAB_W + 2*TAB_SIDE + 1.2, WALL + TAB_TILT + TAB_CLR + 0.6, 0.02]);
            }
        }
        // finger notch(es) in the top rim: expose the door's top edge to pull on
        for (nx = NOTCH_X) translate([nx - NOTCH_WS/2, DOOR_Y0, EXT_H - REB - 0.4])
            cube([NOTCH_WS, EXT_D - DOOR_Y0 + 1, REB + 1]);
    }
}

// ---- splitting the shell for a 220 mm Z ------------------------------------
// Lap joint. The tongue lives INSIDE the wall skin -- an earlier version built
// it from the cavity inward, which put a 1.4 mm bar straight across both drive
// slot floors and gave the two halves a line-to-line fit. Sides and ceiling
// only; the floor butts, where the joint is in compression anyway.
module seam_uband(t_out, t_in, y0, len, t_bot = 0) {
    difference() {
        translate([WALL - t_out, y0, FLOOR_Z - t_bot])
            cube([IN_W + 2*t_out, len, IN_H + t_out + t_bot]);
        translate([WALL + t_in, y0 - 1, FLOOR_Z - 1 - t_bot])
            cube([IN_W - 2*t_in, len + 2, IN_H + 1 - t_in + t_bot]);
    }
}
// A 0.8 x 45 deg lead-in round each corridor at the split, on both halves:
// two prints never meet perfectly, and a drive pushed in (or out) drags its
// corners across this line. dir = +1 for the rear half, -1 for the front.
module corridor_mouth(s, dir) {
    zr = PORT ? PAD_RELIEF : 0;          // the portrait floor is relieved
    hull() {
        translate([s[0] - 0.8, SPLIT_AT - 0.01, s[1] - zr - 0.8])
            cube([SLOT_W + 1.6, 0.02, SLOT_H + zr + 1.6]);
        translate([s[0], SPLIT_AT + dir*0.8 - 0.01, s[1] - zr])
            cube([SLOT_W, 0.02, SLOT_H + zr]);
    }
}
// SEAM SCREW (v8, portrait). The printed box could be pulled apart at the top:
// the drive screws tie the halves together through the floor only, and the
// lap tongue just slides. Two snap latches were drawn (v6 a strap, v7 a bar)
// and neither felt right: join the pieces, then let a SCREW hold them.
// So the roof tongue is thickened into a short boss where the divider is, a
// M2.5 nut slides into a slot in it from the side, and one M2.5 x 10 screw
// (the board's hardware) goes down through the rear half's roof, through the
// tongue, into that nut. The boss reaches 9 mm past the seam, inside the
// rear half's divider, and takes nothing from the drives.
// OFF since v9: no screw on top either. The joint is
// the tighter lap (LIP_CL_OUT) plus the drive screws through the floor.
SEAM_SCREW = false;
SS_XC   = SX0 + SLOT_W + DIV/2;     // divider centreline
SS_Y    = SPLIT_AT + 4.5;           // screw axis: mid-lap
SS_D    = M25_CLEAR;                // M2.5 clearance, as on the door
SS_NAF  = 5.4;                      // nut slot across flats (nut 5.0)
SS_NT   = 2.3;                      // nut slot height (nut 2.0)
SS_NZ   = CEIL_Z - 1.6;             // nut slot's top face: 1.6 of boss over the nut
SS_DEPTH= 8.0;                      // boss below the ceiling: a 10 mm screw ends inside it
SS_Y1   = SPLIT_AT + 9.0;           // boss end
module seam_boss() {
    difference() {
        translate([SS_XC - DIV/2 + 0.3, SPLIT_AT - 2, CEIL_Z - SS_DEPTH])
            cube([DIV - 0.6, SS_Y1 - SPLIT_AT + 2, SS_DEPTH + 0.01]);
        // nut slot, in from either side; its flats bear on the y walls
        translate([SS_XC - DIV/2, SS_Y - SS_NAF/2, SS_NZ - SS_NT]) cube([DIV, SS_NAF, SS_NT]);
        // 45 deg relief under the boss tip so it leads into the rear half
        translate([SS_XC - DIV/2, SS_Y1, CEIL_Z - SS_DEPTH]) rotate([45, 0, 0]) translate([0, -1, -1]) cube([DIV, 2, 2]);
    }
}
module seam_screw_hole() {
    translate([SS_XC, SS_Y, CEIL_Z - SS_DEPTH + 0.6]) cylinder(h = EXT_H, d = SS_D, $fn = 24);
}
module seam_notch() {   // room in the rear divider for the boss
    translate([SX0 + SLOT_W - 0.01, SPLIT_AT - 0.1, CEIL_Z - SS_DEPTH - 0.4])
        cube([DIV + 0.02, SS_Y1 + 1.0 - SPLIT_AT, SS_DEPTH + 0.4 + 0.01]);
}
// SEAM WEDGE (v10). A low ramp on the TOP face of the roof tongue: it starts
// level with the tongue at the tip, so the halves start together easily, and
// rises SEAM_WEDGE over 4 mm to a 1.5 mm crest that sits just inside the rear
// half's mouth. With LIP_CL_OUT 0.05 the crest presses 0.05 into the roof
// skin, which flexes: the last few millimetres of travel tighten up and the
// top of the joint is held by that grip. Roof only; the sides stay a push fit.
SEAM_WEDGE = 0.10;
module seam_wedge() {
    ZT = CEIL_Z + LIP_T;
    translate([WALL + 2, 0, 0]) rotate([90, 0, 90]) linear_extrude(IN_W - 4) polygon([
        [SPLIT_AT + 1.2,           ZT - 0.01],
        [SPLIT_AT + 2.5,           ZT + SEAM_WEDGE],
        [SPLIT_AT + 4.0,           ZT + SEAM_WEDGE],
        [SPLIT_AT + LIP_L - 0.4,   ZT - 0.01]]);
}
// SEAM CLICKS (v11). The halves still opened at the top when the box was lifted.
// Low bumps on the OUTER face of the front half's connecting strip -- three across
// the roof, two down each side near the top -- click into matching dimples in the
// inner face of the rear half's skin. Nothing shows outside. Both bumps and dimples
// have 45-degree flanks: the front half prints standing on its front face, so a
// bump's retaining flank faces the bed and must be self-supporting; the result is
// a firm detent, not a lock -- a hard pull still separates the halves.
SEAM_CLICKS = true;
CLK_H  = 0.40;  CLK_L  = 3.0;  CLK_W  = 6.0;     // bump: height, along the seam, across
CLK_DH = 0.50;  CLK_DL = 3.6;  CLK_DW = 7.0;     // dimple: a little bigger all round
CLK_Y  = SPLIT_AT + LIP_L * 0.6;                 // centre, 4.8 behind the seam face
CLK_ROOF_X = [for (f = [0.2, 0.5, 0.8]) WALL + IN_W * f];
CLK_SIDE_Z = [CEIL_Z - 12, CEIL_Z - 50];
module clk_frustum(l, w, h) {          // stands on z = 0, rises +z, l along y, w along x
    hull() {
        translate([-w/2, -l/2, -0.01]) cube([w, l, 0.02]);
        translate([-(w - 2*h)/2, -(l - 2*h)/2, h - 0.01]) cube([w - 2*h, l - 2*h, 0.01]);
    }
}
module seam_clicks(dimple = false) {   // bumps on the front strip, or the rear skin's dimples
    h = dimple ? CLK_DH : CLK_H;  l = dimple ? CLK_DL : CLK_L;  w = dimple ? CLK_DW : CLK_W;
    gap = dimple ? LIP_CL_OUT : 0;
    for (x = CLK_ROOF_X) translate([x, CLK_Y, CEIL_Z + LIP_T + gap]) clk_frustum(l, w, h);
    for (m = [0, 1]) translate([m ? EXT_W : 0, 0, 0]) mirror([m, 0, 0])
        for (z = CLK_SIDE_Z) translate([WALL - LIP_T - gap, CLK_Y, z]) rotate([0, -90, 0]) clk_frustum(l, w, h);
}
module front_half_box() {
    translate([-10, -10, -10]) cube([EXT_W + 20, SPLIT_AT + 10, EXT_H + 20]);
}
module shell_front() {
    difference() { shell_front_solid(); if (SEAM_SCREW) seam_screw_hole(); }
}
module shell_front_solid() {
    union() {
        difference() {
            intersection() { shell(); front_half_box(); }
            for (s = SLOTS) corridor_mouth(s, -1);
        }
        intersection() {
            difference() {
                seam_uband(LIP_T, 0, SPLIT_AT - 4, LIP_L + 4);
                // 0.4 x 45 lead-in all round the tip. Not 0.8: two 0.8
                // chamfers on a 1.4 band meet 0.7 back and feather it to a
                // knife edge. 0.4 leaves a 0.6 land.
                TIPY = SPLIT_AT + LIP_L;
                for (m = [0, 1]) translate([m ? EXT_W : 0, 0, 0]) mirror([m, 0, 0]) {
                    translate([0,0,-1]) linear_extrude(EXT_H + 2) polygon([
                        [WALL - LIP_T, TIPY], [WALL - LIP_T, TIPY - 0.4],
                        [WALL - LIP_T + 0.4, TIPY]]);
                    translate([0,0,-1]) linear_extrude(EXT_H + 2) polygon([
                        [WALL, TIPY], [WALL, TIPY - 0.4], [WALL - 0.4, TIPY]]);
                }
                // top face of the ceiling band: left square. The rear half's
                // eased mouth (the second, shorter seam_uband) opens the slot
                // 0.45 over its first 2 mm, which is the lead-in that matters
                // there, and the tip has 0.5 of y clearance so it never bottoms.
            }
            translate([0, -1, 0]) cube([EXT_W, SPLIT_AT + LIP_L + 1, EXT_H]);
        }
        if (SEAM_SCREW) seam_boss();
        if (SEAM_WEDGE > 0) seam_wedge();
        if (SEAM_CLICKS) seam_clicks(false);
    }
}
module shell_rear() {
    S_END = SPLIT_AT + LIP_L + 0.5;  S_UP = LIP_T + LIP_CL_OUT;
    difference() {
        shell();
        if (SEAM_SCREW) { seam_notch(); seam_screw_hole(); }
        if (SEAM_CLICKS) seam_clicks(true);
        if (DOOR_CLICKS) door_clicks(true);
        front_half_box();
        seam_uband(LIP_T + LIP_CL_OUT, LIP_CL_IN, SPLIT_AT - 1, LIP_L + 1.5, LIP_CL_IN);
        // eased mouth: the slot's opening IS this half's first millimetre, so
        // first-layer squish lands exactly where the tight fit starts
        seam_uband(LIP_T + LIP_CL_OUT + 0.45, LIP_CL_IN, SPLIT_AT - 1, 2.0, LIP_CL_IN);
        // The socket's END at the ceiling, ramped 45 deg. Square, it was a
        // 1.5 mm ledge held on one side only, half a millimetre in front of
        // the tongue's square tip, and its droop ate the tip clearance.
        translate([WALL - S_UP, 0, 0]) rotate([90, 0, 90]) linear_extrude(IN_W + 2*S_UP)
            polygon([[S_END - 0.01, CEIL_Z - LIP_CL_IN], [S_END - 0.01, CEIL_Z + S_UP],
                     [S_END + S_UP + LIP_CL_IN, CEIL_Z - LIP_CL_IN]]);
        for (s = SLOTS) corridor_mouth(s, 1);
    }
}

// =============================================================================
//  9. MOCK-UPS -- not printed; they exist so clashes show up in the render
// =============================================================================

module gw_board() {
    if (GW_ON_FLOOR) {
        translate([GW_X0, GW_YR - GW_W, GW_ZB]) cube([GW_L, GW_W, GW_PCB_T]);
        // USB-C receptacle on the back edge, opening toward the door
        translate([GW_USB_XF - 4.47, GW_YR - 7, GW_ZB + GW_PCB_T]) cube([8.94, 8, 3.26]);
        // 34-pin IDC shroud along the front edge, facing up
        translate([GW_X0 + GW_L - GW_IDC_X[1], GW_YR - GW_W, GW_ZB + GW_PCB_T])
            cube([GW_IDC_X[1] - GW_IDC_X[0], 9, GW_IDC_H]);
    } else if (GW_ON_END) {
        translate([GW_X0, GW_Y, GW_BOT]) cube([GW_W, GW_PCB_T, GW_L]);
        // USB-C receptacle on the left edge, opening left
        translate([GW_X0 - 1, GW_Y - 3.26, GW_USB[1] - 4.47]) cube([8, 3.26, 8.94]);
        // 34-pin IDC shroud on the right edge, facing the drives
        translate([GW_X0 + GW_W - 9, GW_Y - GW_IDC_H, GW_TOP - GW_IDC_X[1]])
            cube([9, GW_IDC_H, GW_IDC_X[1] - GW_IDC_X[0]]);
    } else {
        translate([GW_X0, GW_Y, GW_Z0]) cube([GW_L, GW_PCB_T, GW_W]);
        // USB-C receptacle, bottom edge, opening downward
        translate([GW_USB[0] - 4.45, GW_Y - 3.26, GW_Z0 - 1]) cube([8.94, 3.26, 8]);
        // 34-pin IDC shroud on the TOP edge, facing the drives
        translate([GW_X0 + GW_IDC_X[0], GW_Y - GW_IDC_H, GW_TOP - 9])
            cube([GW_IDC_X[1] - GW_IDC_X[0], GW_IDC_H, 9]);
    }
}

module cable_run(pts, d) {
    for (i = [0 : len(pts) - 2]) hull() {
        translate(pts[i]) sphere(d = d, $fn = 16);
        translate(pts[i+1]) sphere(d = d, $fn = 16);
    }
}
// The USB-C lead: plug hangs on the receptacle's own axis, so a tug pulls
// it out instead of levering the socket off the board; the cable then has
// USB_DROP of free length before the window's bottom edge.
module usb_cable() {
    ya = GW_Y - GW_PCB_T;
    if (GW_ON_FLOOR) {
        x = GW_USB_XF; z = GW_USB_ZF;
        translate([x - 6.2, GW_YR + 1, z - 3.25]) cube([12.4, PLUG_L, 6.5]);
        cable_run([[x, GW_YR + 1 + PLUG_L, z], [x, GW_YR + PLUG_L + 12, z - 2],
                   [x, GW_YR + PLUG_L + 26, -2], [x, GW_YR + PLUG_L + 66, -2.4]], 5.0);
    } else if (GW_ON_END) {
        x = GW_X0; z = GW_USB[1]; wx = (USB_WIN[0] + USB_WIN[1])/2;
        translate([x - PLUG_L, ya - 3.25, z - 6.2]) cube([PLUG_L, 6.5, 12.4]);
        cable_run([[x - PLUG_L, ya, z], [x - PLUG_L - 6, ya + 1.5, z],
                   [wx + 4, DOOR_Y0 - 2, z - 1], [wx, EXT_D + 2, z - 3],
                   [wx - 2, EXT_D + 14, z - 12], [wx - 3, EXT_D + 30, -2],
                   [wx - 3, EXT_D + 70, -2.4]], 5.0);
    } else {
        x = GW_USB[0];
        translate([x - 6.2, ya - 3.25, GW_Z0 - PLUG_L]) cube([12.4, 6.5, PLUG_L]);
        cable_run([[x, ya, GW_Z0 - PLUG_L], [x, ya + 1, WIN_Z0 + 9],
                   [x, ya + 6, WIN_Z0 + 2], [x, EXT_D + 1, WIN_Z0 - 1],
                   [x, EXT_D + 13, WIN_Z0 - 6], [x, EXT_D + 29, -2],
                   [x, EXT_D + 69, -2.4]], 5.0);
    }
}
// PSU5 lead in the keyhole, mated to the splitter's input on the floor
module pwr_lead() {
    if (GW_ON_FLOOR) {        // in over the board, on to the splitter in front of it
        translate([PWR_CX - 10.5, GW_YR - GW_W - 2 - 42, PWR_CZ - 4]) cube([21, 42, 8]);
        cable_run([[PWR_CX, GW_YR - GW_W - 2, PWR_CZ], [PWR_CX, EXT_D + 2, PWR_CZ],
                   [PWR_CX, EXT_D + 12, PWR_CZ - 6], [PWR_CX, EXT_D + 22, -1],
                   [PWR_CX, EXT_D + 70, -1.4]], 6);
    } else {
    translate([PWR_CX - 10.5, IN_D - 46, FLOOR_Z]) cube([21, 42, 8]);
    cable_run([[PWR_CX, DOOR_Y0 - 4, FLOOR_Z + 4], [PWR_CX, EXT_D + 2, PWR_CZ],
               [PWR_CX, EXT_D + 12, PWR_CZ - 4], [PWR_CX, EXT_D + 22, -1],
               [PWR_CX, EXT_D + 70, -1.4]], 6);
    }
}

// =============================================================================
// 10. REAR DOOR -- clips on, no fasteners. Everything in the rear zone is part
//     of it, so it all leaves with the door and the drives get a clear run in.
//     Prints flat on its OUTER face: the bottom tabs are part of the plate,
//     and the standoffs and clips stand up from it.
// =============================================================================

DOOR_Z0 = SILL_Z;                                // it rests on the sill
DOOR_H  = EXT_H - REB - SILL_Z - 2*PANEL_CLR;    // all the slack at the top
DOOR_X0 = REB + PANEL_CLR;
DOOR_W  = EXT_W - 2*(REB + PANEL_CLR);
DOOR_R  = CORNER_R - REB - 0.3;

// One bottom tab's outline, t thick in y from y0, inset by `ins` all round
// (for the chamfer hull). It reaches 2 mm up into the plate so it unions.
module tab_outline(x, y0, t, ins) {
    r = TAB_R - ins;
    hull() {
        translate([x - TAB_W/2 + ins, y0, DOOR_Z0]) cube([TAB_W - 2*ins, t, 2]);
        for (dx = [-TAB_W/2 + TAB_R, TAB_W/2 - TAB_R])
            translate([x + dx, y0, DOOR_Z0 - TAB_L + TAB_R]) rotate([-90, 0, 0])
                cylinder(h = t, r = r);
    }
}

// DOOR CLICKS (v13). Hidden click tabs on the back panel's two side edges, like the
// seam clicks: two bumps per side click into dimples in the rim of the frame the
// panel sits in, so it is held down its whole height, not only by the top clips.
// Bumps are centred in the panel's 3 mm thickness with 45-degree flanks (the panel
// prints outer face down, so the flank toward the bed must be self-supporting).
DOOR_CLICKS = true;
DCK_H  = PANEL_CLR + 0.35;  DCK_L  = 2.4;  DCK_W  = 8.0;   // bump: 0.35 of engagement past the gap
DCK_DH = DCK_H + 0.10;      DCK_DL = 2.8;  DCK_DW = 9.0;   // dimple in the frame's 1.5 mm rim
module door_clicks(dimple = false) {
    h = dimple ? DCK_DH : DCK_H;  l = dimple ? DCK_DL : DCK_L;  w = dimple ? DCK_DW : DCK_W;
    x0 = dimple ? REB : DOOR_X0;
    for (m = [0, 1]) translate([m ? EXT_W : 0, 0, 0]) mirror([m, 0, 0])
        for (f = [0.3, 0.7]) translate([x0, DOOR_Y0 + WALL/2, DOOR_Z0 + DOOR_H * f]) rotate([0, -90, 0]) clk_frustum(l, w, h);
}
module rear_door() {
    difference() {
        union() {
            translate([DOOR_X0, DOOR_Y0, DOOR_Z0]) rounded_plate(DOOR_W, DOOR_H, WALL, DOOR_R);
            if (DOOR_CLICKS) door_clicks(false);
            // bottom tabs: the plate carried straight down, full thickness
            for (x = TAB_X) tab_outline(x, DOOR_Y0, WALL, 0);
            // board standoffs (only while the board lives on the door)
            for (h = GW_ON_FLOOR ? [] : GW_HOLES)
                translate([h[0], DOOR_Y0 - GW_STANDOFF, h[1]]) rotate([-90,0,0])
                    cylinder(h = GW_STANDOFF + 0.5, d = 6.4);
            // top clips: cantilever beam, 30 deg lead-in, 45 deg return face
            // that cams the tooth DOWN when the door is pulled
            for (x = CLIP_X) translate([x - CLIP_W/2, 0, 0]) rotate([90, 0, 90])
                linear_extrude(CLIP_W) {
                    polygon([[CLIP_Y0 - 1, CLIP_ZT - CLIP_T], [DOOR_Y0 + 0.5, CLIP_ZT - CLIP_T],
                             [DOOR_Y0 + 0.5, CLIP_ZT], [CLIP_Y0 - 1, CLIP_ZT]]);
                    polygon([[CLIP_Y0,               CLIP_ZT - 0.01],
                             [CLIP_Y0 + CLIP_LEAD,   CLIP_ZT + CLIP_H],
                             [CLIP_YR - CLIP_H,      CLIP_ZT + CLIP_H],
                             [CLIP_YR,               CLIP_ZT - 0.01]]);
                    // root fillets, both faces: the root is the plate/beam
                    // layer boundary and a square corner runs Kt ~2 there
                    // Each overlaps the beam by 0.02 AND runs 0.5 into the
                    // door plate. A fillet that merely TOUCHES the beam edge,
                    // or ends flush with the plate face, is a tangent union
                    // and CGAL rejects the result as a non-closed mesh.
                    translate([DOOR_Y0 - CLIP_FIL, CLIP_ZT - 0.02]) difference() {
                        square([CLIP_FIL + 0.5, CLIP_FIL + 0.02]);
                        translate([0, CLIP_FIL + 0.02]) circle(r = CLIP_FIL);
                    }
                    translate([DOOR_Y0 - CLIP_FIL, CLIP_ZT - CLIP_T - CLIP_FIL]) difference() {
                        square([CLIP_FIL + 0.5, CLIP_FIL + 0.02]);
                        circle(r = CLIP_FIL);
                    }
                }
        }
        // elephant-foot chamfer, 0.5 x 45 deg, round the bed-side edge of the
        // whole outline, tabs included (a square step there hung over air)
        difference() {
            translate([DOOR_X0 - 2, DOOR_Y1 - 0.5, DOOR_Z0 - TAB_L - 2])
                cube([DOOR_W + 4, 0.6, DOOR_H + TAB_L + 4]);
            translate([DOOR_X0, 0, DOOR_Z0]) hull() {
                translate([0, DOOR_Y1 - 0.51, 0]) rounded_plate(DOOR_W, DOOR_H, 0.01, DOOR_R);
                translate([0.5, DOOR_Y1 - 0.01, 0.5])
                    rounded_plate(DOOR_W - 1, DOOR_H - 1, 0.02, DOOR_R - 0.5);
            }
            for (x = TAB_X) hull() {
                tab_outline(x, DOOR_Y1 - 0.51, 0.01, 0);
                tab_outline(x, DOOR_Y1 - 0.01, 0.02, 0.5);
            }
        }
        // pull notch in the top edge, under the rim notch: a fingertip curls
        // in and pulls on the door's INNER face. Nothing to bridge.
        for (nx = NOTCH_X)
            translate([nx - NOTCH_WS/2 + 0.2, DOOR_Y0 - 1, DOOR_Z0 + DOOR_H - NOTCH_D])
                rounded_plate(NOTCH_WS - 0.4, NOTCH_D + 8, WALL + 2, 3);
        // Board screws: M2.5 from the BOARD side, through the standoff, into a
        // nut pressed into a hex pocket in the door's OUTER face. The pocket is
        // open to the bed, so its roof is a ring over air; two sacrificial
        // bridge layers (a slot, then a square) give that roof something to
        // span, and the screw goes straight through them.
        for (h = GW_ON_FLOOR ? [] : GW_HOLES) {
            yb = DOOR_Y1 - NUT25_POCKET;                    // the pocket's roof
            translate([h[0], DOOR_Y0 - GW_STANDOFF - 1, h[1]]) rotate([-90,0,0])
                cylinder(h = (yb - 0.4) - (DOOR_Y0 - GW_STANDOFF - 1), d = M25_CLEAR);
            translate([h[0] - NUT25_AF/cos(30)/2 - 0.1, yb - 0.2, h[1] - M25_CLEAR/2])
                cube([NUT25_AF/cos(30) + 0.2, 0.21, M25_CLEAR]);
            translate([h[0] - M25_CLEAR/2, yb - 0.4, h[1] - M25_CLEAR/2])
                cube([M25_CLEAR, 0.21, M25_CLEAR]);
            translate([h[0], yb, h[1]]) rotate([-90,0,0])
                cylinder(h = NUT25_POCKET + 0.01, d = NUT25_AF/cos(30), $fn = 6);
        }
        // USB window: the plug passes through it (with the door off) and the
        // cable leaves through it.
        // Tapered, wider on the OUTSIDE -- it flares the mouth for the plug,
        // rounds the edge the cable leans on, and because the door prints
        // outer face down the taper closes inward, so it needs no support.
        if (!GW_ON_FLOOR) hull() {
            translate([USB_WIN[0], DOOR_Y0 - 1, USB_WIN[2]])
                rounded_plate(USB_WIN[1] - USB_WIN[0], USB_WIN[3] - USB_WIN[2], 1.2, 4);
            translate([USB_WIN[0] - 1.2, DOOR_Y1 - 0.2, USB_WIN[2] - 1.2])
                rounded_plate(USB_WIN[1] - USB_WIN[0] + 2.4, USB_WIN[3] - USB_WIN[2] + 2.4, 1.4, 5.2);
        }
        // USB notch (board on the floor): up from the bottom edge round the plug,
        // rounded at the top; the door drops over the plugged-in cable.
        if (GW_ON_FLOOR) hull() {
            translate([USB_NOTCH[0], DOOR_Y0 - 1, DOOR_Z0 - TAB_L - 1]) cube([USB_NOTCH[1] - USB_NOTCH[0], WALL + 2, 1]);
            for (x = [USB_NOTCH[0] + 2, USB_NOTCH[1] - 2])
                translate([x, DOOR_Y0 - 1, USB_NOTCH[2] - 2]) rotate([-90, 0, 0]) cylinder(h = WALL + 2, r = 2);
        }
        // power: cable hole + slot to the bottom edge. The lead slides in
        // sideways with the door off; the sill closes the slot when it seats;
        // a 21 x 8 plug cannot pull back through a 6.6 hole, so the moulded
        // plug body is the strain relief and nothing loads the crimps.
        translate([PWR_CX, DOOR_Y0 - 1, PWR_CZ]) rotate([-90,0,0])
            cylinder(h = WALL + 2, d = CABLE_D + 0.6);
        translate([PWR_CX - (CABLE_D + 0.4)/2, DOOR_Y0 - 1, -1])
            cube([CABLE_D + 0.4, WALL + 2, PWR_CZ + 1]);
    }
}

// =============================================================================
// 11. FIT TEST RINGS -- print these first, about an hour each. The FRONT ring
//     is the first 12 mm of the front piece: the bezel recess and the start of
//     the corridor, so a drive pushed through it rear-first tests its whole
//     length, and the bezel shows whether it seats flush. The REAR ring is the
//     last 27 mm of the rear piece: the door's rebate, hook pockets and clip
//     catches, so the printed door can be clipped in and out of it.
// =============================================================================

FIT_FRONT_L = 12.0;
FIT_REAR_L  = 27.0;
module fit_front() intersection() {
    shell(); translate([-1, -1, -1]) cube([EXT_W + 2, FIT_FRONT_L + 1, EXT_H + 2]); }
module fit_rear() intersection() {
    shell_rear(); translate([-1, EXT_D - FIT_REAR_L, -1]) cube([EXT_W + 2, FIT_REAR_L + 1, EXT_H + 2]); }

// =============================================================================
// 12. ASSEMBLY + RENDER SELECTOR
// =============================================================================

// The drive SITS on the corridor floor in both layouts; the clearance is all
// overhead (and, across the corridor, split either side).
module drive_mock(s) {
    x0 = s[0]; z0 = s[1];
    translate([x0 + (SLOT_W - DRV_SX)/2, FRAME_Y, z0]) cube([DRV_SX, DRV_D, DRV_SZ]);
    translate([x0 + (SLOT_W - BZ_SX)/2, 0, z0 - (BZ_SZ - DRV_SZ)/2])
        cube([BZ_SX, DRV_BZ_P, BZ_SZ]);
}

module foot(x, y) { translate([x, y, -FOOT_H + FOOT_REC]) cylinder(h = FOOT_H, d = FOOT_D - 0.4); }
module all_feet() {
    for (x = [FOOT_INSET_X, EXT_W - FOOT_INSET_X],
         y = [FOOT_Y_FRONT, FOOT_Y_REAR]) foot(x, y);
}

module assembly(explode = 0) {
    color("#E8E0D2") shell();
    // 0.05 lift: the mock's underside is coplanar with the slot floor, which
    // makes the assembly preview export non-manifold. Mock only, not printed.
    color("#BFB6A4") for (s = SLOTS) translate([0, 0, 0.05]) drive_mock(s);
    color("#D4CBB8") translate([0, explode*1.6, 0]) rear_door();
    color("#2F6B45") translate([0, explode*1.4, 0]) gw_board();
    color("#151515") translate([0, explode*1.4, 0]) usb_cable();
    color("#2B2B2B") translate([0, explode*1.6, 0]) pwr_lead();
    color("#3A352E") translate([0, 0, -explode*0.7]) all_feet();
}

PART = "assembly";   // overridden by -D or by an including file

if      (PART == "fit_front")     fit_front();
else if (PART == "fit_rear")      fit_rear();
else if (PART == "shell")         shell();
// (these two are only meaningful when SPLIT_AT > 0)
else if (PART == "shell_front")   { if (SPLIT_AT > 0) shell_front(); else shell(); }
else if (PART == "shell_rear")    { if (SPLIT_AT > 0) shell_rear();  else shell(); }
else if (PART == "rear_panel")    rear_door();
else if (PART == "gw_board")      gw_board();
else if (PART == "drive_a")       drive_mock(SLOTS[0]);
else if (PART == "drive_b")       drive_mock(SLOTS[1]);
else if (PART == "feet")          all_feet();
else if (PART == "usb_cable")     usb_cable();
else if (PART == "pwr_lead")      pwr_lead();
else if (PART == "assembly")      assembly(0);
else if (PART == "exploded")      assembly(55);

// ---- sanity echoes -----------------------------------------------------------
RP_CLIP_LEFF = DOOR_Y0 - (CLIP_YR - CLIP_H/2);
// What sits under the head: washer + plastic. What's left goes into the drive.
CB_Z_HERE  = PORT ? CBORE_Z : CBORE_ZS;
SCREW_PLAS = (PORT ? FLOOR_Z - (PADS ? 0 : PAD_RELIEF) : WALL + SIDE_MARGIN) - CB_Z_HERE + SEAT_T;
SCREW_L    = SIX32 ? 9.53                          //  3/8", both layouts
                   : (PORT ? SCREW_PLAS + 4.5 : SCREW_PLAS + 3.5);
SCREW_IN   = SCREW_L - SCREW_PLAS;
SCREW_CALL = SIX32 ? "#6-32 x 3/8\" pan head on a #6 SAE flat washer" : str("M3 x ", SCREW_L);
SCREW_MAJ  = SIX32 ? 3.51 : 3.0;
HOLE_PRINT = SCREW_CLEAR - HOLE_FUDGE;
ABSORB     = (HOLE_PRINT - SCREW_MAJ) / 2;
// The seat: the washer's annulus over the printed hole, less the longest slot.
// Torque that holds it at 10 MPa -- a stress PETG carries for months without
// creeping the clamp away:  F = 10 * A,  T = 0.2 * d * F
BEAR_A  = PI/4 * (SEAT_D*SEAT_D - HOLE_PRINT*HOLE_PRINT) - HOLE_PRINT*max(HOLE_Y_SLOT, HOLE_Y_SLOT_A);
TQ_MAX  = 0.2 * SCREW_MAJ/1000 * 10 * BEAR_A;
// The front face, at the bed: every bar of first layer between and round the
// bezel recesses (the side bars lose FRONT_CH to the corner chamfer).
RX0  = [for (s = SLOTS) s[0] + (SLOT_W - BZ_SX - BZ_CLR_X)/2];
RZ0  = [for (s = SLOTS) s[1] - (BZ_SZ - DRV_SZ + BZ_CLR_Z)/2];
RW   = BZ_SX + BZ_CLR_X;   RH = BZ_SZ + BZ_CLR_Z;
FACE = PORT ? [RX0[0] - FRONT_CH, RX0[1] - RX0[0] - RW, EXT_H - RZ0[0] - RH, RZ0[0]]
            : [RX0[0] - FRONT_CH, RZ0[1] - RZ0[0] - RH, EXT_H - RZ0[1] - RH, RZ0[0]];
assert(min(FACE) >= 1.2, str("*** a first-layer bar on the front face is under 1.2 mm: ", FACE, " ***"));
// How far the bezel overhangs the corridor at each edge -- what it stops on.
// It is rigid, so one real overlap stops it; the bottom one is always there,
// because the drive sits on the floor and the bezel hangs below its frame.
BZ_OVER_X   = (BZ_SX - SLOT_W)/2;                                   // each side
BZ_OVER_BOT = (BZ_SZ - DRV_SZ)/2 - (PORT ? PAD_RELIEF : 0);          // floor
BZ_OVER_TOP = DRV_SZ + (BZ_SZ - DRV_SZ)/2 - SLOT_H;                  // top (may be < 0)
assert(max(BZ_OVER_X, BZ_OVER_BOT) >= 0.5, "*** the bezel has nothing to stop on ***");

echo(str("ORIENT ..................... ", ORIENT));
echo(str("EXTERNAL ................... ", EXT_W, " W x ", EXT_H, " H x ", EXT_D, " D mm"));
echo(str("INTERNAL ................... ", IN_W, " W x ", IN_H, " H x ", IN_D, " D"));
echo(str("  drive bay ", BAY_W, " x ", BAY_H, ", divider ", DIV,
         ", rails ", SIDE_MARGIN, " each side, floor ", FLOOR_Z));
echo(str("Drive corridor ............. ", SLOT_W, " x ", SLOT_H, " for a ", DRV_SX, " x ", DRV_SZ,
         " drive; bezel ", BZ_SX, " x ", BZ_SZ, " in a ", RW, " x ", RH, " x ", FRAME_Y,
         " recess. Bezel overhangs the corridor ", BZ_OVER_X, " each side, ", BZ_OVER_BOT,
         " at the floor, ", BZ_OVER_TOP, " at the top: it loads from the FRONT and stops flush"));
echo(str("Front face bars (bed) ...... side ", FACE[0], ", between recesses ", FACE[1],
         ", top ", FACE[2], ", bottom ", FACE[3], " mm"));
echo(str("Board vs the walls ......... ", GW_ON_END ? str("on its end, x ", GW_X0, "..", GW_X0 + GW_W, " in an interior ", WALL, "..", WALL + IN_W)
                                               : str(GW_L, " board in ", IN_W, " -> ", (IN_W - GW_L)/2, " a side")));
echo(str("Board vs the drives ........ board front face y ", GW_Y,
         " vs the drive's rear connectors reaching ", FRAME_Y + DRV_D + 12.5,
         "  ->  clear by ", GW_Y - (FRAME_Y + DRV_D + 12.5)));
echo(str("Drive screws ............... ", PORT ? "VERTICAL up through the floor"
                                              : "HORIZONTAL through both side walls",
         "  ->  ", SCREW_CALL, " (", SCREW_L, " mm: washer + plastic ", SCREW_PLAS, ", ",
         SCREW_IN, " into the drive, max ", MAX_ENGAGE,
         SCREW_IN > MAX_ENGAGE ? "  *** TOO LONG ***" : " OK", ")",
         PORT ? "" : str("; less the gap to the wall, up to ", FIT_SLOP, " on one side if the drive isn't centred")));
echo(str("  station ", HOLE_Z, " above the drive's bottom face, which faces ",
         PORT ? (PORT_PCB_RIGHT ? "RIGHT" : "LEFT") : "DOWN", " (",
         SIX32 ? "#6-32 set" : "M3 set", "); the other set is at ",
         SIX32 ? HOLE_M3_Z : HOLE_632_Z, " and is left undrilled"));
echo(str("Tolerance budget ........... hole prints ", HOLE_PRINT, " on a ",
         SCREW_MAJ, " screw -> +/-", ABSORB,
         "; A (+/-0.5, drive pushed back on its bezel) accepts -", ABSORB + HOLE_Y_SLOT_A, "..+", ABSORB,
         "; B (+/-1.0) accepts +/-", ABSORB + HOLE_Y_SLOT/2,
         (ABSORB >= 0.5 && ABSORB + HOLE_Y_SLOT/2 >= 1.0) ? "  OK" : "  *** SHORT ***"));
echo(str("Drive screw torque ......... stop at ", round(TQ_MAX*100)/100,
         " N.m (snug with a short driver, no wrist): the washer seats on ",
         round(BEAR_A*10)/10, " mm2 of PETG at the worst station = 10 MPa"));
echo(str("Screw heads ................ #6 pan + washer (", HEAD_H + SEAT_T, " tall) in ",
         CBORE_D, " x ", CB_Z_HERE, " -> ", HEAD_H + SEAT_T - CB_Z_HERE, " proud",
         PORT ? str(" of the floor, against ", FOOT_H - FOOT_REC, " of ground clearance")
              : " of the side walls, where nothing bears on it"));
echo(str("Board screw ................ M2.5 x ", GW_PCB_T + GW_STANDOFF + (WALL - NUT25_POCKET) + 2.0,
         " exactly (board ", GW_PCB_T, " + standoff ", GW_STANDOFF, " + web ", WALL - NUT25_POCKET,
         " + nut 2.0): tip level with the nut, ", NUT25_POCKET - 2.0, " inside the door's back"));
echo(str("Back panel ................. recessed ", DOOR_RECESS, " in its frame, on a ", SILL_Z,
         " mm sill; ", len(TAB_X), " tabs ", TAB_W, " x ", TAB_L, " into slots with ",
         EXT_D - DOOR_Y1 - TAB_CLR, " of skin behind and ", TAB_TILT, " of tilt room in front"));
echo(str("Door clip .................. ", CLIP_W, " x ", CLIP_T, " x ", CLIP_L,
         ", tooth ", CLIP_H, " (", CLIP_OVER, " proud), release approx ",
         round(2 * 1.857 * 3*2000*(CLIP_W*pow(CLIP_T,3)/12)*CLIP_OVER/pow(RP_CLIP_LEFF,3)),
         " N total  (over the ROOT-to-contact length ", RP_CLIP_LEFF, ")"));
// board guards: the screws must land on the door plate, the nut pockets
// inside it, the board clear of the clip beams, the power slot clear of the tabs
GW_HZ_MIN = min([for (h = GW_HOLES) h[1]]);
assert(GW_ON_FLOOR || GW_HZ_MIN - 3.2 >= DOOR_Z0 + 0.5, "*** a board standoff runs off the door's bottom edge ***");
assert(GW_ON_FLOOR || GW_HZ_MIN - NUT25_AF/2 >= DOOR_Z0 + 1.0, "*** a nut pocket breaks out of the door's bottom edge ***");
// floor board guards
assert(!GW_ON_FLOOR || IN_W - GW_L >= 1.0, "*** the board does not fit across the interior ***");
assert(!GW_ON_FLOOR || GW_YR - GW_W >= FRAME_Y + DRV_D + 12.5 + 2, "*** the board runs into the drives' rear connectors ***");
assert(!GW_ON_FLOOR || USB_NOTCH[0] >= DOOR_X0 + 3, "*** the USB notch is too close to the door's edge ***");
assert(!GW_ON_FLOOR || min([for (t = TAB_X) max(USB_NOTCH[0] - (t + TAB_W/2), (t - TAB_W/2) - USB_NOTCH[1])]) >= 2,
       "*** the USB notch runs into a bottom tab ***");
assert(!GW_ON_FLOOR || max(USB_NOTCH[0] - (PWR_CX + CABLE_D/2), (PWR_CX - CABLE_D/2) - USB_NOTCH[1]) >= 4,
       "*** the USB notch runs into the power slot ***");
assert(!GW_ON_FLOOR || min([for (h = GW_FHOLES, x = [FOOT_INSET_X, EXT_W - FOOT_INSET_X])
                             norm([h[0] - x, h[1] - FOOT_Y_REAR])]) >= FOOT_RING/2 + NUT25_AF/cos(30)/2 + 1,
       "*** a board nut pocket runs into a rear foot ***");
assert(!GW_ON_FLOOR || PWR_CZ - CABLE_D/2 >= GW_ZB + GW_PCB_T + 9, "*** the power lead enters below the board's parts ***");
if (GW_ON_FLOOR)
    echo(str("Board on the floor ......... x ", GW_X0, "..", GW_X0 + GW_L, " (", (IN_W - GW_L)/2, " a side), y ",
             GW_YR - GW_W, "..", GW_YR, " (front edge ", GW_YR - GW_W - (FRAME_Y + DRV_D + 12.5),
             " clear of the drive connectors), underside z ", GW_ZB, "; USB-C at x ", GW_USB_XF, " z ", GW_USB_ZF,
             ", notch x ", USB_NOTCH[0], "..", USB_NOTCH[1], " to z ", USB_NOTCH[2], "; power hole z ", PWR_CZ,
             "; screw M2.5 x ", GW_PCB_T + GW_FSTAND + GW_FWEB + 2.0, " (board + post + web + nut); rear feet at y ",
             FOOT_Y_REAR, "; tabs at x ", TAB_X));
GW_X1 = GW_ON_END ? GW_X0 + GW_W : GW_X0 + GW_L;
assert(GW_ON_FLOOR || GW_TOP < CLIP_ZT - CLIP_T - 1 || (GW_X0 > CLIP_X[0] + CLIP_W/2 + 2 && GW_X1 < CLIP_X[1] - CLIP_W/2 - 2),
       "*** the board sits under a door clip ***");
assert(min([for (t = TAB_X) abs(PWR_CX - t)]) >= TAB_W/2 + CABLE_D/2 + 2, "*** the power slot runs into a bottom tab ***");
assert(GW_ON_FLOOR || (USB_WIN[2] - 1.2 >= DOOR_Z0 + 3 && USB_WIN[0] - 1.2 >= DOOR_X0 + 3), "*** the USB window is too close to the door's edge ***");
if (!GW_ON_FLOOR) echo(str("Greaseweazle ............... ", GW_ON_END ? "on its END" : "lying", ", board x ", GW_X0, "..", GW_X1,
         ", z ", GW_BOT, "..", GW_TOP, GW_BOT < FLOOR_Z ? str(" (foot ", FLOOR_Z - GW_BOT, " into a floor pocket)") : "",
         ", USB-C at ", GW_USB, GW_ON_END ? " facing left" : " facing down",
         ", window x ", USB_WIN[0], "..", USB_WIN[1], " z ", USB_WIN[2], "..", USB_WIN[3],
         ", power hole x ", PWR_CX,
         "; finger notch(es) at x ", NOTCH_X, ", ", NOTCH_WS, " wide"));
GW_GAP = CEIL_Z - GW_TOP;
if (!GW_ON_FLOOR) echo(str("Box height set by .......... ",
         TOP_CLEAR > TOP_CLEAR_MIN ? "THE BOARD" : "the drives",
         "   (board top ", GW_TOP, ", ceiling ", CEIL_Z, ", clear by ", GW_GAP, ")"));
echo(str("Feet ....................... ", FOOT_D, " dia x ", FOOT_H, " at x ", FOOT_INSET_X,
         " and ", EXT_W - FOOT_INSET_X, " -> ground clearance ", FOOT_H - FOOT_REC,
         ", stance ", EXT_W - 2*FOOT_INSET_X, " of ", EXT_W, " wide"));
echo(str("Print on the FRONT face .... footprint ", EXT_W, " x ", EXT_H,
         SPLIT_AT > 0 ? str(", Z = ", SPLIT_AT + LIP_L, " and ", EXT_D - SPLIT_AT,
                            " for the two halves")
                      : str(", Z = ", EXT_D, " in one piece")));
// Guards. Stacked, the drive screws run out through the side walls, so the lap
// tongue and the seam groove must keep clear of both stations' counterbores.
function span_hits(a0, a1, b0, b1) = (a0 < b1 && a1 > b0);
CB_Y  = [for (i = [0, 1])
           let (y = STATION_Y[i],
                lo = (i == 0) ? HOLE_Y_SLOT_A : HOLE_Y_SLOT/2,
                hi = (i == 0) ? 0 : HOLE_Y_SLOT/2)
             [y - lo - CBORE_D/2 - 0.8, y + hi + CBORE_D/2 + 0.8]];
LAP_Y = [SPLIT_AT - 4, SPLIT_AT + LIP_L];
LAP_BAD = (PORT || SPLIT_AT <= 0) ? false
        : len([for (c = CB_Y) if (span_hits(c[0], c[1], LAP_Y[0], LAP_Y[1])) 1]) > 0;
echo(SPLIT_AT <= 0
  ? "Lap joint ................. none -- the shell is one piece"
  : str("Lap joint ................. y ", LAP_Y[0], "..", LAP_Y[1],
        PORT ? "   (portrait screws go through the FLOOR; the lap joint has no floor band)"
             : str("   vs screw counterbores ", CB_Y, " -> ",
                   LAP_BAD ? "*** CLASH: the tongue or groove sits on a drive screw ***" : "clear")));
echo(str("Divider ................... ",
         PORT ? str("x ", SX0+SLOT_W, "..", SX0+SLOT_W+DIV)
              : str("z ", FLOOR_Z+SLOT_H, "..", FLOOR_Z+SLOT_H+DIV),
         ", y 1..", FRAME_Y + DRV_D));
echo(str("Top/floor vents ........... y ", [for (y = DUCT_Y) [y, y + DUCT_LEN]], ", ",
         len(VENT_XB), " group(s) x ", VENT_NX, " slots, x ",
         [for (xb = VENT_XB) [xb + VENT_DX, xb + SLOT_W - VENT_DX]],
         PLATE ? str("; corridor plate + roof webs at x ", WEB_X) : ""));
echo(SPLIT_AT > 0
  ? str("SPLIT at y=", SPLIT_AT, ": front piece ", SPLIT_AT + LIP_L,
        " tall (", SPLIT_AT, " of shell + ", LIP_L, " of tongue), rear ",
        EXT_D - SPLIT_AT, ". Held by the DRIVES: station A (", STATION_Y[0],
        ") in the front piece, B (", STATION_Y[1], ") in the rear")
  : str("ONE PIECE: needs a printer with Z >= ", EXT_D, " mm"));

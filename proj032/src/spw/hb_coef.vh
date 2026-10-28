// hb_coef.vh — light・final の係数（runs/m0_coef.json、M-0 の模型が正）。hbmc・hb2 の H に渡す（H[j*18 +: 18] = h[j]）
localparam integer LIGHT_N = 15;
localparam integer LIGHT_SH = 17;
localparam [18*15-1:0] LIGHT_H = {-18'sd393, 18'sd0, 18'sd2436, 18'sd0, -18'sd9156, 18'sd0, 18'sd39878, 18'sd65542, 18'sd39878, 18'sd0, -18'sd9156, 18'sd0, 18'sd2436, 18'sd0, -18'sd393};
localparam integer FINAL_N = 67;
localparam integer FINAL_SH = 18;
localparam [18*67-1:0] FINAL_H = {18'sd212, 18'sd0, -18'sd251, 18'sd0, 18'sd393, 18'sd0, -18'sd583, 18'sd0, 18'sd831, 18'sd0, -18'sd1150, 18'sd0, 18'sd1555, 18'sd0, -18'sd2064, 18'sd0, 18'sd2705, 18'sd0, -18'sd3518, 18'sd0, 18'sd4565, 18'sd0, -18'sd5955, 18'sd0, 18'sd7891, 18'sd0, -18'sd10815, 18'sd0, 18'sd15877, 18'sd0, -18'sd27305, 18'sd0, 18'sd83206, 18'sd130955, 18'sd83206, 18'sd0, -18'sd27305, 18'sd0, 18'sd15877, 18'sd0, -18'sd10815, 18'sd0, 18'sd7891, 18'sd0, -18'sd5955, 18'sd0, 18'sd4565, 18'sd0, -18'sd3518, 18'sd0, 18'sd2705, 18'sd0, -18'sd2064, 18'sd0, 18'sd1555, 18'sd0, -18'sd1150, 18'sd0, 18'sd831, 18'sd0, -18'sd583, 18'sd0, 18'sd393, 18'sd0, -18'sd251, 18'sd0, 18'sd212};

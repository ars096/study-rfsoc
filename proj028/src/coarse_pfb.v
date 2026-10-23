// SPDX-License-Identifier: BSD-3-Clause
// proj028 C-1 — 荒い PFB（tools/gen_coarse_pfb.py が作る。手で直さない）
// 入力 1 拍 16 サンプル（[16p+2 +: 14]、p = 拍の中の時間の順）。ブロック m の最も新しいサンプルは 56m + 55（拍の数え 7 拍に 2 回）
// z_r = sat18((Σ_t g[r + 64t]·x[t0 − r − 64t] + 2^17) >>> 18)、g は (−1)^t を含む 18 bit。model/coarse_pfb_ref.py と bit 単位で同じ
`default_nettype none
module coarse_pfb (
    input  wire          clk,
    input  wire          rst,              // 拍の数え（ブロックの位相）だけを戻す。履歴はリセットしない
    input  wire          s_valid,
    input  wire [255:0]  s_data,
    output reg           m_valid,
    output wire [1151:0] m_z               // z_r（r = 0..63）、各 18 bit
);
    localparam integer L = 1728, NH = 1736, XW = 14, CW = 18;
    localparam [CW*L-1:0] G = 31104'hfff2fffcafff2bffcbfff2fffccfff37ffcefff3fffd0fff4bffd4fff5fffd9fff73ffdffff8bffe5fffa7ffedfffc7fff5fffe7fffe00008000700030001100058001c000840027000b00031000dc003c00108004700130005100158005b001800064001a0006c001c00073001dc0079001f0007e002000081002080082002080082002040080001f8007c001e40076ffe3bff92ffe5fff9cffe87ffa7ffebbffb5ffef3ffc4fff37ffd5fff7bffe7fffc7fffb00014000f000680025000c0003b001180051001700067001c8007c0021c00910027000a5002bc00b80030400c90034400d80037c00e5003a800ef003cc00f7003e400fb003f000fd003f000fb003e000f5003c400ec0039800e00036000d00031800bc002c400a500264008bffe0fff92ffe87ffb1fff0bffd3fff97fff700024001c000bc004300158006a001f400910029000b80032c00dd003c001020044c0124004d001440054c0160005b4017900610018e0065c019f0069401aa006b801b1006c801b2006c001ad006a001a20066801910061c017b005b4015f00538013d004a801150040000e90034400b80027800830019c004b000b4000f0003c002e00138006e0023400ad0033400ed00434012c0052801690061801a3006f801d9007cc020b00888023800930025f009c0027f00a34029800a8402a900ab802b100ac802b100ab802a800a80029600a24027a009a40255008fc02270083401f10074c01b200640016c0051c011f003dc00cc002840074001180018fffa3ffb8ffe23ff57ffc9bfef5ffb13fe930067401cd007ec022900958028100aac02d300be8031e00d04036100dfc039b00ed003ca00f7403ee00fec040601034041101048040f0102403ff00fc803e200f3803b700e70037e00d74033900c4402e600ae0028800954021f0079801ab005b8012f003b800ac001a00023fff77ff96ffd3bff06ffafbfe76ff8bbfde7ff683fd5bff45ffcd4ff24ffc54ff063fbdd01168048f0130404ef0146c05420159405850168005b80172805d90178805e70179c05e20176405ca016d8059e01600055e014dc050b0136804a5011ac042d00fa803a400d64030b00ae802650083401b30055800f6002540032fff3bff68ffc0bfe9bff8d7fdceff5a3fd03ff27ffc3dfef73fb7efec8bfac9fe9d3fa22fe74ff989fe513f903fe31bf890fe17bf83301fcc0813020b4084002130085202144084a020ec08260202407e601eec078a01d48071401b3c0683018c405da015f00519012c0044300f40035900b78025f007740158003400046ffeebff2cffa7bfe0fff603fcf2ff193fbd8fed37fac5fe8fff9bdfe4fbf8c3fe137f7dcfddc3f70afdaabf651fd7fff5b4fd5c3f535fd407f4d6fd2d3f49afd22bf482fd213f49002d6c0b3d02c540ae302aa00a630285809bf0257c08f602214080c01e2c0702019c805da014f4049900fc0034200a3c01d8004740060ffe83fedeff86ffd57ff253fbd1fec3ffa4ffe64bf8d8fe087f76ffdb0bf61bfd5ebf4e0fd137f3c2fcd03f2c7fc95ff1f1fc657f144fc3fff0c5fc25bf074fc17bf055fc167f069fc21bf0b0fc39ff12bfc5f3f1dafc913f2bb033080c3302e640af30290c09890231007f601c8006410156c046e00de80282006100082ffdf7fe76ff5b7fc63fed67fa50fe527f844fdd0ff647fd53ff45dfcdcbf28ffc6d7f0e3fc073ef60fbabfee0afb5cbece8fb1afebfefae7feb50fac47eae3fab17eab8faaf3ead2fabebeb33fadfbebdafb123ecc7fb55fedf8fbaabef6bfc0f7f11dfc837f30afd057f52c026c0088201d240606012ec03690084000b1ffd3bfde7ff1fbfb14fe6abf841fdb6bf577fd063f2befc5b3f022fbb87edaafb1ffeb61fa93fe94dfa16be777f9a9be5e8f94f3e4a5f9087e3b4f8d73e31af8bbfe2dbf8b7fe2fbf8cbfe37bf8f7fe45cf93c3e59cf9983e73bfa0b7e935fa94feb86fb337ee28fbe5bf115fca97f445fd7d3f7affe5dffb4aff49fff0bffc2bfd19fec97f92ffdce3f542fcd3ff160fbddfed95faef7e9eefa0b7e679f9353e340f86ffe051f7be7ddb8f723bdb7df6a1fd9acf63bbd84df5f2bd767f5c8fd700f5bfbd71df5d7fd7c2f611fd8eff66e7daa4f6ecbdce1f78c3dfa0f84bfe2ddf92a3e690fa253eab2fb3a7ef37fc673f414fda83f93cfef9ffea00058c043001c0c09db032d80f91049a8153ff9fcfe52ef89d3dfc8f74b3daa2f60b7d5cef4e27d160f3d4fcd67f2e73c9f5f21cfc719f179fc4e0f1017c358f0b67c28bf09b7c281f0b23c342f0fc3c4d2f17a3c733f22c7ca64f312bce63f42bbd32af575bd8b2f6eebdeeff8937e5d4fa60bed53fc51ff559fe627fdd2008cc06a802cb80fc2051841907076c4225c09c0c2ba30c0e034bf0e4cc3d911075845fced7ffb21feb9a7aae0e9e23a465e85eb9ecae716b9a2ce611396a5e554b944fe4e73933fe4ce3938ae50e39543e5ab79878e6a979d35e80aba384e9d0fab68ebfd3b4e5ee8f3bff8f1867cc9df4e0fdacaf89bfea72fcb3ffb85012400def05e7821990af783669104d44c4015e1062fe1baa47a8121a0092a227b88ab3a2de98c4203428cdd2a3a6b8f62b40a690ef7b9312d89eb326ac0bfad44ea99ba796e935aa22727e279d0026a2a982b2578993b1a46688f9c636e68bf2e292388bc61d3985ff6133f83c0a0b488204e056580cfa01a08022e000180006008b80682033e81596081382d220f0284cfe17fd874e622f18a48e2fcb8db9a3e71919a24ec695e2660ac9a8aa74009f89e889ca4d6a9e5baa66eb513b02fecc9ab627ae4c443bdd029a3d8ace9ae374a8d0a331080b7a62ace89ee224a8886801ea046ea918bf857841310041350d9a42bde08664179e037bc0490fee17f2cffa9cbe26ff6b2bd383f3277c619effe3ba3ced397aff4eada3a743e8e13a02ae74d79aa5e61e396ade550f9438e4e2b9338e4cff939ce513f9552e5a979844e68b39c5ae7b2ba17ae9197a788eab83ae69ec87fb5ff117f041d60f64439330d2fc30380ae8c2703089701db10641c146103f080b2e01aa00233ff74bf989fd567f147fb54fe982f9753e24df7bbfdbbaf62cbd5d6f4cabd0aef398fcc4af2993c8b1f1ccfc5e8f134bc3f0f0d0bc2c8f0a07c26df0a2fc2d9f0d63c405f1383c5e7f1c67c873f27d7cb9cf359fcf53f4583d389f573bd82df6a8bdd2cf7f23e274f94bbe7f3054fc126a03e440cb60276c0703010c00163ffa83fbe7fe4f3f6a0fd053f19cfbcdfece9faacbe894f9a43e4a8f8b77e12ff7e83de30f7387dbb2f6a93d9b9f63bfd847f5f0bd75ff5c77d6fef5c03d723f5d9fd7caf6137d8eef66b3da87f6df7dc8ef76e3def9f8147e1bff8d03e4d4f99e7e82dfa7bbebbdfb657ef77fc583f34ffd50bf738fe4bffb25ff467ff0affc2ffd27fed2bf977fdebff5f4fd117f2a5fc457ef96fb8a3eccdfae1bea53fa4d7e82df9cefe660f9673e4f0f9173e3dff8defe32ff8befe2dff8b6fe2eff8c6be35cf8ed3e421f9297e53cf97a3e6a6f9ddfe85afa537ea4ffad87ec7ffb6abeee1fc08bf16cfcafbf418fd5dff6dafe107f9aafec53fc7eff79fff4e002c4021000da404bb0181807490220809b0fd4b3f415fcc2bf20dfc477f03dfbdafeeaafb7e3ed57fb31fec48faf6beb7efaccfeafafab4beabcfaae3eac5fab8feb11fad43eb9ffaffbec6bfb3a3ed72fb82beeaffbd83f01cfc38ff1b5fca3ff372fd177f54ffd91ff743fe113f949fe943fb59ff18ffd6dff9dbff7d00208018400a08037a011b8055b01904072001fd808c4026240a4302bcc0b99030cc0cc2fcaeff244fc76bf17cfc4aff0e7fc2c3f086fc1a7f059fc157f05efc1d3f096fc317f0fffc513f195fc7c7f257fcb1ff340fcf0bf44dfd383f57afd86ff6c2fddbff821fe363f992fe93ffb0ffef47fc94ff55ffe1bffb7bffa000180011d00760028f00d0803f001264053d01768067201c08078b020300885023d8095f026fc0a160298c0aa802b8c0b1502cf40b5bfd243f484fd20bf48afd26bf4b4fd35bf501fd4d7f570fd6d3f5fffd947f6aafdc2bf770fdf73f84dfe30ff93efe6f7fa3ffeb17fb4dfef63fc64ff3cbfd80ff83ffe9effcb3ffba0011800d00056001dd0097c02de00d6403d00110c04b001464057c01768063101a0c06cf01c50075201e2807bb01f98080902098083b02128085102148084c02100082d0204c07f3fe0cff85efe243f8c6fe40ff944fe627f9d3fe88bfa74feb27fb22fedfbfbdcff0f7fc9fff40ffd68ff73bfe35ffa6fff02ffda3ffce000c80095003d80156006cc020d0099402ba00c2c035900e9003ea010b4046b0129404da0142c05370157805800167805b60172805d90178805e70179c05e20176405ca016e005a001614056501508051b013bc04c10123c045afef77fc18ff153fc93ff353fd17ff56ffda0ff79ffe2eff9dbfebeffc1bff4effe5bffdd0008c0068002b000ee004bc016e006ac01e60087c025500a2002b800b98031100ce4035d00df8039c00edc03ce00f8803f200ffc04090103c041201044040d0101803fb00fb803dd00f2803b400e6c037f00d84034100c7802fa00b4c02ab00a040256008a401fb00734019dffa4ffec4ffbd7ff26ffd5fff88ffee3ffe8000600046001d000a10033000f70047c0147005b00190006c801d3007c4020d0089c023f009540269009e8028900a5802a000aa002ae00ac402b200ac402ae00aa402a100a60028d009fc02700097c024c008e002220082c01f30076401be0068c0186005a4014a004b0010d003b400cd002b4008d001b8004e000b8000f0003c002d0012c00670020c009e002e000d1003a4010000454012a004f4014e0057c016d005ec018700644019a0068801a8006b401b0006c801b2006c401ae006a801a50067c0197006380184005e4016d0058001530051001340049001130040800f00037400cb002e000a400244007d001a800560010c002f000700009fffdfffe5fff4fffc2ffec7ffa1ffe4bff830022c00990029400b1002f000c60034000d80038000e6003b000f1003d400f8003ec00fc003f400fc003ec00f9003dc00f3003bc00ea0039400df0036000d10032400c1002e000af00294009c002440087001f000720019c005c001440046000ec003000094001a0003c0005fffeffff1fff9fffdefff57ffcdfff13ffbcffed7ffaeffe9fffa1ffe73ff97ffe4bff8e001d80079001f0007e002000081002080082002080082002040080001f8007c001e40077001cc0070001b000680019000600016c005600144004c0011c0042000f00037000c4002c0009c002100070001600044000c0001c0002ffffbfff9fffd7fff1fffb7ffe9fff97ffe2fff7fffdcfff67ffd7fff53ffd2fff43ffcffff3bffcdfff33ffcbfff2fffcafff2bffcb;
    // ---- 履歴（新しいほど小さい番号: H[0] = 今の拍の 15 番）----
    reg [XW*NH-1:0] H;
    integer p;
    reg [XW*16-1:0] nb;
    always @* for (p = 0; p < 16; p = p + 1) nb[XW*(15-p) +: XW] = s_data[16*p + 2 +: XW];
    always @(posedge clk) if (s_valid) H <= {H[XW*(NH-16)-1:0], nb};
    // ---- 拍の数え（7 拍に 2 ブロック）: 拍 3 → 位相 B（H[n + 8]）、拍 6 → 位相 A（H[n]）。数えは履歴に入った拍の番号 ----
    reg [2:0] b7;
    reg       v1;
    always @(posedge clk) begin
        v1 <= s_valid;
        if (rst) b7 <= 3'd0;
        else if (v1) b7 <= (b7 == 3'd6) ? 3'd0 : b7 + 3'd1;
    end
    // v1 の拍で H は拍 b7 を最新に持つ
    wire blk_a = v1 && !rst && (b7 == 3'd6);
    wire blk_b = v1 && !rst && (b7 == 3'd3);
    // ---- 窓の写し S[n] = x[t0 − n] ----
    reg [XW*L-1:0] S;
    always @(posedge clk) begin
        if (blk_a) S <= H[XW*L-1:0];
        else if (blk_b) S <= H[XW*(L+8)-1:XW*8];
    end
    // ---- 3 拍の計算: 拍 c（0..2）に DSP (r, k) が n = r + 64(3k + c) ----
    reg [1:0] c;          // 0..2 計算中、3 休み
    always @(posedge clk) begin
        if (rst) c <= 2'd3;
        else if (blk_a || blk_b) c <= 2'd0;
        else if (c != 2'd3) c <= c + 2'd1;
    end
    reg [1:0] c1, c2, c3, c4, c5;
    always @(posedge clk) begin c1 <= c; c2 <= c1; c3 <= c2; c4 <= c3; c5 <= c4; end
    genvar r, k;
    generate for (r = 0; r < 64; r = r + 1) begin : g_r
        wire signed [31:0] pr [0:8];
        for (k = 0; k < 9; k = k + 1) begin : g_k
            reg signed [XW-1:0] xs;
            reg signed [CW-1:0] gs;
            (* use_dsp = "yes" *) reg signed [XW+CW-1:0] m1, m2;
            always @(posedge clk) begin
                case (c)
                    2'd0: begin xs <= S[XW*(r + 64*(3*k + 0)) +: XW]; gs <= G[CW*(r + 64*(3*k + 0)) +: CW]; end
                    2'd1: begin xs <= S[XW*(r + 64*(3*k + 1)) +: XW]; gs <= G[CW*(r + 64*(3*k + 1)) +: CW]; end
                    2'd2: begin xs <= S[XW*(r + 64*(3*k + 2)) +: XW]; gs <= G[CW*(r + 64*(3*k + 2)) +: CW]; end
                    default: begin xs <= {XW{1'b0}}; gs <= {CW{1'b0}}; end
                endcase
                m1 <= xs * gs;
                m2 <= m1;
            end
            assign pr[k] = m2;
        end
        // 9 個の和（2 段）→ 3 拍ぶん積む
        reg signed [36:0] s0, s1, s2, sa;
        always @(posedge clk) begin
            s0 <= pr[0] + pr[1] + pr[2];
            s1 <= pr[3] + pr[4] + pr[5];
            s2 <= pr[6] + pr[7] + pr[8];
            sa <= s0 + s1 + s2;
        end
        reg signed [37:0] acc;
        reg signed [17:0] zr;
        wire signed [37:0] accn = (c5 == 2'd0) ? sa : acc + sa;
        wire signed [37:0] rnd = (accn + (1 <<< 17)) >>> 18;
        always @(posedge clk) begin
            acc <= accn;
            if (c5 == 2'd2) zr <= (rnd > 131071) ? 131071 : (rnd < -131071) ? -131071 : rnd[17:0];
        end
        assign m_z[18*r +: 18] = zr;
    end endgenerate
    // 遅れ: c = 0 の拍 → xs（+1）→ m1（+2）→ m2（+3）→ s（+4）→ sa（+5）→ acc（c5 = c の 5 拍後に積む）。c5 == 2 で zr、その次の拍に valid
    always @(posedge clk) m_valid <= !rst && (c5 == 2'd2);
endmodule
`default_nettype wire

/*
 * Product Dimensions Auto-Populator
 * Matches product handles to Ashley Furniture dimension data
 * and injects it into the Dimensions tab.
 *
 * TO ADD A PRODUCT: Add a new entry to the DIMENSIONS object below.
 * Key = product handle (from the URL), Value = HTML string with dimensions.
 */

const DIMENSIONS = {
  'ophannon-sectional': `
    <h3 style="margin:0 0 16px;font-size:1em;font-weight:600">O'Phannon 2-Piece Sectional with Chaise</h3>
    <table><thead><tr><th>Piece</th><th>Width</th><th>Depth</th><th>Height</th><th>Weight</th></tr></thead>
    <tbody>
      <tr><td><strong>Overall Sectional</strong></td><td>125"</td><td>86"</td><td>38"</td><td>260 lbs</td></tr>
      <tr><td><strong>LAF Sofa Chaise</strong></td><td>87"</td><td>61"</td><td>38"</td><td>147 lbs</td></tr>
      <tr><td><strong>RAF Corner Chaise</strong></td><td>37"</td><td>86"</td><td>38"</td><td>113 lbs</td></tr>
    </tbody></table>
    <div style="margin-top:16px">
      <p style="margin:0 0 4px;font-weight:600;font-size:.9em">Additional Measurements</p>
      <p style="margin:0;font-size:.9em;line-height:1.8">Seat Depth: 23" · Seat Height: 21" · Arm Height: 26"</p>
    </div>`,

  'rawcliffe-3-piece-sectional': `
    <h3 style="margin:0 0 16px;font-size:1em;font-weight:600">Rawcliffe 3-Piece Sectional</h3>
    <table><thead><tr><th>Piece</th><th>Width</th><th>Depth</th><th>Height</th><th>Weight</th></tr></thead>
    <tbody>
      <tr><td><strong>Overall Sectional</strong></td><td>131"</td><td>131"</td><td>38"</td><td>340 lbs</td></tr>
      <tr><td><strong>LAF Sofa</strong></td><td>86"</td><td>44"</td><td>38"</td><td>135 lbs</td></tr>
      <tr><td><strong>Wedge</strong></td><td>45"</td><td>44"</td><td>38"</td><td>83 lbs</td></tr>
      <tr><td><strong>RAF Sofa</strong></td><td>86"</td><td>44"</td><td>38"</td><td>135 lbs</td></tr>
    </tbody></table>
    <div style="margin-top:16px">
      <p style="margin:0 0 4px;font-weight:600;font-size:.9em">Additional Measurements</p>
      <p style="margin:0;font-size:.9em;line-height:1.8">Seat Depth: 24" · Seat Height: 21" · Arm Height: 26"</p>
    </div>`,

  'rawcliffe-4-piece-sectional': `
    <h3 style="margin:0 0 16px;font-size:1em;font-weight:600">Rawcliffe 4-Piece Sectional</h3>
    <table><thead><tr><th>Piece</th><th>Width</th><th>Depth</th><th>Height</th><th>Weight</th></tr></thead>
    <tbody>
      <tr><td><strong>Overall Sectional</strong></td><td>170"</td><td>131"</td><td>38"</td><td>423 lbs</td></tr>
      <tr><td><strong>LAF Sofa</strong></td><td>86"</td><td>44"</td><td>38"</td><td>135 lbs</td></tr>
      <tr><td><strong>Wedge</strong></td><td>45"</td><td>44"</td><td>38"</td><td>83 lbs</td></tr>
      <tr><td><strong>Armless Chair</strong></td><td>39"</td><td>44"</td><td>38"</td><td>70 lbs</td></tr>
      <tr><td><strong>RAF Sofa</strong></td><td>86"</td><td>44"</td><td>38"</td><td>135 lbs</td></tr>
    </tbody></table>
    <div style="margin-top:16px">
      <p style="margin:0 0 4px;font-weight:600;font-size:.9em">Additional Measurements</p>
      <p style="margin:0;font-size:.9em;line-height:1.8">Seat Depth: 24" · Seat Height: 21" · Arm Height: 26"</p>
    </div>`,

  'barrelton-sectional': `
    <h3 style="margin:0 0 16px;font-size:1em;font-weight:600">Barrelton Modular Sectional</h3>
    <table><thead><tr><th>Piece</th><th>Width</th><th>Depth</th><th>Height</th><th>Weight</th></tr></thead>
    <tbody>
      <tr><td><strong>Corner Chair</strong></td><td>41"</td><td>41"</td><td>37"</td><td>75 lbs</td></tr>
      <tr><td><strong>Armless Chair</strong></td><td>30"</td><td>41"</td><td>37"</td><td>58 lbs</td></tr>
      <tr><td><strong>Corner Chaise</strong></td><td>41"</td><td>64"</td><td>37"</td><td>92 lbs</td></tr>
    </tbody></table>
    <div style="margin-top:16px">
      <p style="margin:0 0 4px;font-weight:600;font-size:.9em">Additional Measurements</p>
      <p style="margin:0;font-size:.9em;line-height:1.8">Seat Depth: 23" · Seat Height: 20" · Arm Height: 26" · Modular — configure any arrangement</p>
    </div>`
};

(function() {
  const dimTab = document.getElementById('tab-dimensions');
  if (!dimTab) return;

  // Get product handle from URL
  const path = window.location.pathname;
  const match = path.match(/\/products\/([^/?#]+)/);
  if (!match) return;
  const handle = match[1].toLowerCase();

  // Try exact match first
  let html = DIMENSIONS[handle];

  // Try partial match if no exact match
  if (!html) {
    for (const [key, val] of Object.entries(DIMENSIONS)) {
      if (handle.includes(key) || key.includes(handle)) {
        html = val;
        break;
      }
    }
  }

  if (html) {
    // Find the variant table or CTA and insert dimensions BEFORE it
    const existingTable = dimTab.querySelector('table');
    const cta = dimTab.querySelector('.product-tabs__cta');

    if (existingTable) {
      existingTable.insertAdjacentHTML('beforebegin', html);
      // Keep the CTA but hide the fallback variant table
      existingTable.style.display = 'none';
    } else if (cta) {
      cta.insertAdjacentHTML('beforebegin', html);
    } else {
      // Just prepend to the tab
      dimTab.insertAdjacentHTML('afterbegin', html);
    }
  }
})();

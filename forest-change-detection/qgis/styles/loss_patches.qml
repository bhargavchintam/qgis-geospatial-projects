<!DOCTYPE qgis PUBLIC 'http://mrcc.com/qgis.dtd' 'SYSTEM'>
<qgis version="3.28.0" styleCategories="Symbology">
  <!-- Forest loss patches (forest_loss_patches.gpkg): graduated fill on area_ha. -->
  <renderer-v2 type="graduatedSymbol" attr="area_ha" graduatedMethod="GraduatedColor" symbollevels="0" forceraster="0" enableorderby="0">
    <ranges>
      <range lower="0.000" upper="1.000" symbol="0" label="0.0 - 1.0 ha" render="true"/>
      <range lower="1.000" upper="2.500" symbol="1" label="1.0 - 2.5 ha" render="true"/>
      <range lower="2.500" upper="5.000" symbol="2" label="2.5 - 5.0 ha" render="true"/>
      <range lower="5.000" upper="100000.000" symbol="3" label="&gt; 5.0 ha" render="true"/>
    </ranges>
    <symbols>
      <symbol type="fill" name="0" alpha="0.85" clip_to_extent="1" force_rtl="0">
        <layer class="SimpleFill" enabled="1" locked="0" pass="0">
          <Option type="Map">
            <Option type="QString" name="color" value="254,204,92,255"/>
            <Option type="QString" name="outline_color" value="80,80,80,255"/>
            <Option type="QString" name="outline_style" value="solid"/>
            <Option type="QString" name="outline_width" value="0.26"/>
            <Option type="QString" name="style" value="solid"/>
          </Option>
        </layer>
      </symbol>
      <symbol type="fill" name="1" alpha="0.85" clip_to_extent="1" force_rtl="0">
        <layer class="SimpleFill" enabled="1" locked="0" pass="0">
          <Option type="Map">
            <Option type="QString" name="color" value="253,141,60,255"/>
            <Option type="QString" name="outline_color" value="80,80,80,255"/>
            <Option type="QString" name="outline_style" value="solid"/>
            <Option type="QString" name="outline_width" value="0.26"/>
            <Option type="QString" name="style" value="solid"/>
          </Option>
        </layer>
      </symbol>
      <symbol type="fill" name="2" alpha="0.85" clip_to_extent="1" force_rtl="0">
        <layer class="SimpleFill" enabled="1" locked="0" pass="0">
          <Option type="Map">
            <Option type="QString" name="color" value="240,59,32,255"/>
            <Option type="QString" name="outline_color" value="80,80,80,255"/>
            <Option type="QString" name="outline_style" value="solid"/>
            <Option type="QString" name="outline_width" value="0.26"/>
            <Option type="QString" name="style" value="solid"/>
          </Option>
        </layer>
      </symbol>
      <symbol type="fill" name="3" alpha="0.85" clip_to_extent="1" force_rtl="0">
        <layer class="SimpleFill" enabled="1" locked="0" pass="0">
          <Option type="Map">
            <Option type="QString" name="color" value="189,0,38,255"/>
            <Option type="QString" name="outline_color" value="80,80,80,255"/>
            <Option type="QString" name="outline_style" value="solid"/>
            <Option type="QString" name="outline_width" value="0.26"/>
            <Option type="QString" name="style" value="solid"/>
          </Option>
        </layer>
      </symbol>
    </symbols>
    <source-symbol>
      <symbol type="fill" name="0" alpha="0.85" clip_to_extent="1" force_rtl="0">
        <layer class="SimpleFill" enabled="1" locked="0" pass="0">
          <Option type="Map">
            <Option type="QString" name="color" value="240,59,32,255"/>
            <Option type="QString" name="outline_color" value="80,80,80,255"/>
            <Option type="QString" name="outline_style" value="solid"/>
            <Option type="QString" name="outline_width" value="0.26"/>
            <Option type="QString" name="style" value="solid"/>
          </Option>
        </layer>
      </symbol>
    </source-symbol>
    <colorramp type="gradient" name="[source]">
      <Option type="Map">
        <Option type="QString" name="color1" value="254,204,92,255"/>
        <Option type="QString" name="color2" value="189,0,38,255"/>
        <Option type="QString" name="stops" value="0.5;240,59,32,255"/>
      </Option>
    </colorramp>
    <classificationMethod id="Custom">
      <symmetricMode enabled="0" symmetrypoint="0" astride="0"/>
      <labelFormat format="%1 - %2" labelprecision="1" trimtrailingzeroes="1"/>
      <extraInformation/>
    </classificationMethod>
    <rotation/>
    <sizescale/>
  </renderer-v2>
  <layerGeometryType>2</layerGeometryType>
</qgis>
